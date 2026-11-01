"""Single-worker job queue: one GPU job at a time, same model family first, /free when idle.

16 GB VRAM / 32 GB RAM cannot hold the image and music models together, and two GPU jobs at once stall
each other (measured 2026-09-24), so this worker is the only thing that runs generation.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from ..comfy.client import ComfyClient, ComfyError, ComfyUnavailable
from ..comfy.launcher import ComfyLauncher
from ..config import Settings
from ..store.db import Database, now
from ..store.models import Job
from .runners import JobCancelled, RunContext

log = logging.getLogger(__name__)

Runner = Callable[[RunContext, Job], Awaitable[None]]
COMFYUI_DOWN = "comfyui_down"
# Families that run in the cloud and leave the GPU alone (animations: sprite-gen + codex). They need no ComfyUI, and
# they do not change which models are loaded. The MVP still runs them in this one queue, so GPU jobs wait behind
# them (roadmap Out of Scope: a separate cloud queue).
CLOUD_FAMILIES = ("codex",)
# Jobs that use neither ComfyUI nor the GPU (laying out a book). They wait in the queue like the rest but touch nothing.
LOCAL_FAMILIES = ("none",)


class JobQueue:
    def __init__(
        self,
        db: Database,
        comfy: ComfyClient,
        settings: Settings,
        runners: dict[str, Runner],
        launcher: ComfyLauncher | None = None,
    ):
        self.db = db
        self.comfy = comfy
        self.settings = settings
        self.runners = runners
        self.launcher = launcher
        self.current_family: str | None = None
        self.models_loaded = False
        self.running_job_id: str | None = None
        self._wake = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._run_task: asyncio.Task | None = None
        self._run_done: asyncio.Event | None = None
        self._cancel_requested: set[str] = set()

    async def start(self) -> None:
        stale = self.db.mark_stale_running_failed()
        if stale:
            log.warning("marked %d job(s) left running by a previous process as failed", stale)
        self._worker = asyncio.create_task(self._work(), name="aiassetstudio-queue")

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
        self._worker = None
        if self.models_loaded:
            # The idle /free cannot run once the backend is gone; leave the shared GPU the way we found it.
            try:
                await asyncio.wait_for(self.comfy.free(), timeout=5)
                log.info("stopping: freed ComfyUI memory (POST /free)")
            except (ComfyError, TimeoutError) as e:
                log.warning("POST /free while stopping failed: %s", e)
            self.models_loaded = False

    def notify(self) -> None:
        """Wake the worker after a job was added."""
        self._wake.set()

    async def cancel(self, job_id: str) -> Job | None:
        job = self.db.get_job(job_id)
        if job is None:
            return None
        if job.status == "queued":
            return self.db.update_job(job_id, status="cancelled", finished_at=now())
        if job.status == "running" and job_id == self.running_job_id and self._run_task is not None:
            self._cancel_requested.add(job_id)
            done = self._run_done
            self._run_task.cancel()  # the worker then interrupts the ComfyUI prompt and records the result
            try:
                await asyncio.wait_for(done.wait(), timeout=10)
            except TimeoutError:
                log.warning("job %s did not stop within 10 s of being cancelled", job_id)
            return self.db.get_job(job_id)
        return job  # already finished

    async def _work(self) -> None:
        while True:
            self._wake.clear()  # clear before looking, so a notify() after the lookup is not lost
            job = self.db.next_queued_job(prefer_family=self.current_family)
            if job is None:
                await self._idle()
            else:
                await self._run(job)

    async def _idle(self) -> None:
        if not self.models_loaded:
            await self._wake.wait()
            return
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=self.settings.idle_free_seconds)
        except TimeoutError:
            log.info("queue idle for %g s: freeing ComfyUI memory (POST /free)", self.settings.idle_free_seconds)
            try:
                await self.comfy.free()
            except ComfyError as e:
                log.warning("POST /free failed: %s", e)
            self.models_loaded = False
            self.current_family = None

    async def _run(self, job: Job) -> None:
        runner = self.runners.get(job.kind)
        if runner is None:
            self.db.update_job(job.id, status="failed", error=f"no runner for job kind {job.kind!r}", finished_at=now())
            return
        timeouts = {"bgm": self.settings.bgm_timeout, "animation": self.settings.animation_timeout}
        timeout = timeouts.get(job.kind, self.settings.image_timeout)
        self.db.update_job(job.id, status="running", started_at=now(), stage="starting")
        log.info("job %s started (%s/%s)", job.id, job.kind, job.family)
        ctx = RunContext(self.db, self.comfy, self.settings, cancel_requested=lambda: job.id in self._cancel_requested)
        self.running_job_id = job.id
        self._run_done = asyncio.Event()
        self._run_task = asyncio.create_task(
            self._start_comfy_then_run(runner, ctx, job, timeout), name=f"job-{job.id}"
        )
        status, error = "done", None
        comfy_down = False
        try:
            try:
                await self._run_task
            except TimeoutError:
                status, error = "failed", f"timeout after {timeout:g} s"
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():  # the queue itself is stopping
                    self.db.update_job(job.id, status="failed", error="interrupted by shutdown", finished_at=now())
                    raise
                status = "cancelled"
            except JobCancelled:
                status = "cancelled"
            except ComfyUnavailable as e:
                status, error, comfy_down = "failed", f"{COMFYUI_DOWN}: {e}", True
            except Exception as e:
                if job.id in self._cancel_requested:
                    status = "cancelled"  # e.g. the interrupted prompt surfaced as an execution error
                else:
                    if not isinstance(e, ComfyError):
                        log.exception("job %s crashed", job.id)
                    status, error = "failed", str(e) or type(e).__name__

            if status != "done" and not comfy_down:
                await self._abort_comfy(ctx)
            final = {"status": status, "error": error, "finished_at": now()}
            if ctx.freed_before:  # merged last: runners write their own timings and would overwrite it
                final["timings"] = (self.db.get_job(job.id).timings or {}) | {"free_before": True}
            self.db.update_job(job.id, **final)
            log.info("job %s %s%s", job.id, status, f": {error}" if error else "")
            if not comfy_down and job.family not in (*CLOUD_FAMILIES, *LOCAL_FAMILIES):
                self.current_family = job.family
                self.models_loaded = True
        finally:
            self.running_job_id = None
            self._run_task = None
            self._cancel_requested.discard(job.id)
            self._run_done.set()

    async def _start_comfy_then_run(self, runner: Runner, ctx: RunContext, job: Job, timeout: float) -> None:
        if job.family in LOCAL_FAMILIES:
            await asyncio.wait_for(runner(ctx, job), timeout)
            return
        if job.family in CLOUD_FAMILIES:
            # The GPU sits unused for the minutes this job takes, yet the idle /free cannot run while the worker is
            # busy: give the shared GPU back now, as the idle rule would.
            if self.models_loaded and await self._free_before(ctx, job, "a cloud job"):
                self.current_family = None
            await asyncio.wait_for(runner(ctx, job), timeout)
            return
        # Starting ComfyUI can take up to 2 minutes; it happens inside the job task so a cancel stops it too,
        # but outside the runner's time limit.
        if self.launcher is not None and not await self.comfy.is_up():
            self.db.update_job(job.id, stage="starting ComfyUI")
            await self.launcher.ensure()
        if self.models_loaded and self.current_family not in (None, job.family):
            # Image and music models do not fit together in 16 GB VRAM / 32 GB RAM: Qwen's text encoder (9.4 GB)
            # and model (7.3 GB) plus ACE-Step's (8.4 GB + 4.8 GB) overflow RAM.
            await self._free_before(ctx, job, f"switching {self.current_family} -> {job.family}")
        await asyncio.wait_for(runner(ctx, job), timeout)

    async def _free_before(self, ctx: RunContext, job: Job, why: str) -> bool:
        """POST /free before a job; True if it worked (a failed free leaves the models counted as loaded)."""
        self.db.update_job(job.id, stage="freeing memory")
        try:
            await self.comfy.free()
        except ComfyError as e:
            log.warning("POST /free before job %s failed: %s", job.id, e)
            return False
        ctx.freed_before = True
        self.models_loaded = False
        log.info("job %s: freed ComfyUI memory before %s", job.id, why)
        return True

    async def _abort_comfy(self, ctx: RunContext) -> None:
        """Stop this job's newest ComfyUI prompt, whether running or still queued, and nothing else."""
        if not ctx.prompt_ids:
            return
        prompt_id = ctx.prompt_ids[-1]
        for action in (self.comfy.interrupt, lambda pid: self.comfy.delete_queued([pid])):
            try:
                await action(prompt_id)
            except ComfyError as e:
                log.warning("could not abort ComfyUI prompt %s: %s", prompt_id, e)
