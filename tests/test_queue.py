import asyncio
import dataclasses
from types import SimpleNamespace

import pytest
from fakes import FakeComfy

from aiassetstudio.comfy.client import ComfyClient, ComfyUnavailable
from aiassetstudio.config import Settings
from aiassetstudio.jobs.queue import JobQueue
from aiassetstudio.jobs.runners import run_image_job
from aiassetstudio.store.db import Database


@pytest.fixture
async def env(tmp_path):
    made = []

    async def make(fail_with=None, runner=None, **settings_overrides):
        fake = FakeComfy(fail_with=fail_with)
        comfy = ComfyClient("http://comfy.test", transport=fake.transport)
        db = Database(tmp_path / "studio.db")
        settings = dataclasses.replace(
            Settings(data_dir=tmp_path, idle_free_seconds=3600, image_timeout=5, bgm_timeout=5), **settings_overrides
        )
        order: list[str] = []

        async def record(ctx, job):
            order.append(job.id)

        run = runner or record
        queue = JobQueue(db, comfy, settings, runners={"image": run, "bgm": run, "animation": run})
        e = SimpleNamespace(fake=fake, comfy=comfy, db=db, queue=queue, order=order, settings=settings)
        e.project = db.create_project("demo", "Demo")
        made.append(e)
        return e

    yield make
    for e in made:
        await e.queue.stop()
        await e.comfy.aclose()
        e.db.close()


def add_job(e, family="qwen", **params):
    kind = {"qwen": "image", "codex": "animation"}.get(family, "bgm")
    job = e.db.create_job(e.project.id, kind, family, {"kind": "sprite", "description": "x", **params})
    e.queue.notify()
    return job


async def wait_status(e, job_id, *statuses, timeout=3.0):
    async with asyncio.timeout(timeout):
        while (job := e.db.get_job(job_id)).status not in statuses:
            await asyncio.sleep(0.01)
    return job


async def test_fifo_order(env):
    e = await env()
    jobs = [add_job(e) for _ in range(3)]
    await e.queue.start()
    for job in jobs:
        await wait_status(e, job.id, "done")
    assert e.order == [j.id for j in jobs]


async def test_same_family_first(env):
    gate = asyncio.Event()
    order = []

    async def gated(ctx, job):
        order.append(job.id)
        if len(order) == 1:
            await gate.wait()

    e = await env(runner=gated)
    first = add_job(e, "qwen")
    await e.queue.start()
    await wait_status(e, first.id, "running")
    music = add_job(e, "ace")  # older than `image`, but a different model family
    image = add_job(e, "qwen")
    gate.set()
    await wait_status(e, music.id, "done")
    assert order == [first.id, image.id, music.id]


async def test_timeout_fails_and_interrupts_only_own_prompt(env):
    async def slow(ctx, job):
        ctx.prompt_ids.append("11111111-2222-3333-4444-555555555555")
        await asyncio.sleep(30)

    e = await env(runner=slow, image_timeout=0.2)
    job = add_job(e)
    await e.queue.start()
    failed = await wait_status(e, job.id, "failed")
    assert failed.error == "timeout after 0.2 s"
    assert e.fake.interrupts == ["11111111-2222-3333-4444-555555555555"]
    assert e.fake.deleted == ["11111111-2222-3333-4444-555555555555"]


async def test_cancel_queued(env):
    e = await env()
    job = add_job(e)
    cancelled = await e.queue.cancel(job.id)
    assert cancelled.status == "cancelled"
    await e.queue.start()
    later = add_job(e)
    await wait_status(e, later.id, "done")
    assert e.order == [later.id]
    assert await e.queue.cancel("nope") is None


async def test_cancel_running(env):
    e = await env(fail_with="hang", runner=run_image_job)
    job = add_job(e, count=2, seed=1)
    await e.queue.start()
    await wait_status(e, job.id, "running")
    async with asyncio.timeout(3):
        while not e.fake.prompts:
            await asyncio.sleep(0.01)

    cancelled = await e.queue.cancel(job.id)
    assert cancelled.status == "cancelled"
    [prompt_id] = e.fake.prompts
    assert e.fake.interrupts == [prompt_id]
    assert e.db.list_assets(job_id=job.id) == []
    assert e.queue.running_job_id is None
    done = await e.queue.cancel(job.id)  # already finished: unchanged
    assert done.status == "cancelled"


async def test_restart_marks_stale_running_failed(env):
    e = await env()
    stale = add_job(e)
    e.db.update_job(stale.id, status="running")
    await e.queue.start()
    failed = await wait_status(e, stale.id, "failed")
    assert failed.error == "interrupted by restart"
    assert e.order == []


async def test_idle_free_once(env):
    e = await env(idle_free_seconds=0.2)
    job = add_job(e)
    await e.queue.start()
    await wait_status(e, job.id, "done")
    assert e.queue.current_family == "qwen"
    await asyncio.sleep(0.7)
    assert e.fake.free_calls == [{"unload_models": True, "free_memory": True}]
    assert e.queue.models_loaded is False
    assert e.queue.current_family is None


async def test_stop_frees_loaded_models(env):
    e = await env()
    job = add_job(e)
    await e.queue.start()
    await wait_status(e, job.id, "done")
    assert e.fake.free_calls == []  # idle free is an hour away in this setup
    await e.queue.stop()
    assert e.fake.free_calls == [{"unload_models": True, "free_memory": True}]
    await e.queue.stop()  # stopping twice is harmless and frees nothing more
    assert len(e.fake.free_calls) == 1


async def test_comfyui_down_and_errors(env):
    async def failing(ctx, job):
        if job.params["description"] == "down":
            raise ComfyUnavailable("connection refused")
        raise RuntimeError("boom")

    e = await env(runner=failing, idle_free_seconds=0.1)
    down = add_job(e, description="down")
    await e.queue.start()
    assert (await wait_status(e, down.id, "failed")).error == "comfyui_down: connection refused"
    await asyncio.sleep(0.3)
    assert e.fake.free_calls == []  # nothing was loaded, so nothing to free

    crash = add_job(e, description="crash")
    assert (await wait_status(e, crash.id, "failed")).error == "boom"


class FakeLauncher:
    def __init__(self, fake: FakeComfy, fails: bool = False):
        self.fake = fake
        self.fails = fails
        self.calls = 0

    async def ensure(self):
        self.calls += 1
        await asyncio.sleep(0.05)
        if self.fails:
            raise ComfyUnavailable("ComfyUI did not start within 120 s; see comfyui.log")
        self.fake.down = False


async def test_starts_comfyui_before_running(env):
    e = await env(image_timeout=0.2)
    e.queue.launcher = FakeLauncher(e.fake)
    e.fake.down = True
    job = add_job(e)
    await e.queue.start()
    await wait_status(e, job.id, "done")  # the launch time does not count against the 0.2 s runner limit
    assert e.queue.launcher.calls == 1
    assert e.order == [job.id]


async def test_comfyui_launch_failure(env):
    e = await env()
    e.queue.launcher = FakeLauncher(e.fake, fails=True)
    e.fake.down = True
    job = add_job(e)
    await e.queue.start()
    failed = await wait_status(e, job.id, "failed")
    assert failed.error == "comfyui_down: ComfyUI did not start within 120 s; see comfyui.log"
    assert e.order == []


async def test_stop_marks_running_job(env):
    started = asyncio.Event()

    async def forever(ctx, job):
        started.set()
        await asyncio.sleep(30)

    e = await env(runner=forever)
    job = add_job(e)
    await e.queue.start()
    await started.wait()
    await e.queue.stop()
    stopped = e.db.get_job(job.id)
    assert (stopped.status, stopped.error) == ("failed", "interrupted by shutdown")


async def test_family_switch_frees_memory_once(env):
    async def write_timings(ctx, job):
        ctx.db.update_job(job.id, timings={"candidates": [{"generate": 1.0}]})  # runners write their own timings

    e = await env(runner=write_timings)
    image = add_job(e, "qwen")
    await e.queue.start()
    await wait_status(e, image.id, "done")
    same = add_job(e, "qwen")
    await wait_status(e, same.id, "done")
    assert e.fake.free_calls == []  # same family: nothing to free
    music = add_job(e, "ace")
    done = await wait_status(e, music.id, "done")
    assert e.fake.free_calls == [{"unload_models": True, "free_memory": True}]
    assert done.timings == {"candidates": [{"generate": 1.0}], "free_before": True}
    again = add_job(e, "ace")
    assert (await wait_status(e, again.id, "done")).timings == {"candidates": [{"generate": 1.0}]}
    assert len(e.fake.free_calls) == 1
    assert e.queue.current_family == "ace"


async def test_cloud_family_gives_the_gpu_back_and_needs_no_comfyui(env):
    stages = []

    async def record_stage(ctx, job):
        stages.append(ctx.db.get_job(job.id).stage)

    e = await env(runner=record_stage)
    e.queue.launcher = FakeLauncher(e.fake)
    image = add_job(e, "qwen")
    await e.queue.start()
    await wait_status(e, image.id, "done")
    assert e.queue.launcher.calls == 0  # ComfyUI is up
    e.fake.down = True  # a cloud job must not start ComfyUI...
    cloud = add_job(e, "codex")
    done = await wait_status(e, cloud.id, "done")
    assert e.queue.launcher.calls == 0
    # It tries to free the models the image job left loaded; with ComfyUI down that fails, and the models still
    # count as loaded, so the next job of another family frees them first.
    assert done.timings is None
    assert (e.queue.models_loaded, e.queue.current_family) == (True, "qwen")
    assert stages == ["starting", "freeing memory"]  # image job, then the cloud job right after its (failed) free


async def test_cloud_family_frees_once_and_keeps_the_gpu_state(env):
    e = await env(idle_free_seconds=3600)
    image = add_job(e, "qwen")
    await e.queue.start()
    await wait_status(e, image.id, "done")
    cloud = add_job(e, "codex")
    done = await wait_status(e, cloud.id, "done")
    assert e.fake.free_calls == [{"unload_models": True, "free_memory": True}]  # at the cloud job's start
    assert done.timings == {"free_before": True}
    assert (e.queue.models_loaded, e.queue.current_family) == (False, None)  # not "codex": no GPU models
    after = add_job(e, "qwen")
    assert (await wait_status(e, after.id, "done")).timings is None  # nothing left to free
    assert len(e.fake.free_calls) == 1
    assert (e.queue.models_loaded, e.queue.current_family) == (True, "qwen")


async def test_cloud_jobs_back_to_back_free_nothing(env):
    e = await env()
    first = add_job(e, "codex")
    second = add_job(e, "codex")
    await e.queue.start()
    await wait_status(e, first.id, "done")
    await wait_status(e, second.id, "done")
    assert e.fake.free_calls == []
    assert e.queue.models_loaded is False


async def test_animation_time_limit(env):
    async def slow(ctx, job):
        await asyncio.sleep(30)

    e = await env(runner=slow, image_timeout=30, animation_timeout=0.2)
    job = add_job(e, "codex")
    await e.queue.start()
    assert (await wait_status(e, job.id, "failed")).error == "timeout after 0.2 s"
