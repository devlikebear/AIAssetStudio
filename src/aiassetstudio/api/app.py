"""FastAPI backend: the only process that talks to ComfyUI and runs GPU jobs.

The MCP server and the web gallery are thin clients of this API.
"""

import asyncio
import json
import logging
import shutil
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, get_args

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..comfy import preflight
from ..comfy.client import ComfyClient, ComfyError, ComfyUnavailable
from ..comfy.launcher import ComfyLauncher
from ..config import REPO_ROOT, Settings
from ..jobs.queue import JobQueue
from ..jobs.runners import RUNNERS
from ..spritegen.access import animation_status
from ..store.db import Database, DuplicateSlug, now
from ..store.files import db_path, export_stem, from_rel, unique_stem
from ..store.models import TERMINAL_STATUSES, Asset, AssetStatus, Job, JobStatus, Project
from ..store.reference import ReferenceImageError, load_reference, store_reference
from .schemas import (
    AnimationJobCreate,
    AssetOut,
    AssetUpdate,
    BgmJobCreate,
    ExportRequest,
    ExportResult,
    ImageJobCreate,
    JobCreated,
    JobOut,
    ProjectCreate,
    ProjectUpdate,
    missing_pixel_fields,
)

log = logging.getLogger(__name__)

# GET /object_info is ~1.8 MB and takes ~0.8 s, and the gallery polls the status, so cache the preflight (and the
# animation check, which runs `codex login status`).
PREFLIGHT_TTL = 60.0
LONG_POLL_INTERVAL = 0.5
GALLERY_DIST = REPO_ROOT / "web" / "dist"
# File roles an export copies, per kind; the first group whose files the asset has. A BGM exports its WAV (seamless
# loop) and its OGG (small) together, from the loop if it has one.
EXPORT_FILES = {
    "sprite": (("processed",),),
    "icon": (("processed",),),
    "bgm": (("loop_wav", "loop_ogg"), ("full_wav", "full_ogg")),
}
MEDIA_TYPES = {  # Windows' mimetypes lacks some
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".gif": "image/gif",
    ".json": "application/json",
}
NOT_NULL_PROJECT_FIELDS = ("name", "style", "pixel_art", "animation_cloud")  # in a PATCH, null leaves these
LOCAL_HOSTS = ("127.0.0.1", "localhost")
ANY_ADDRESS = ("0.0.0.0", "::")


def allowed_hosts(settings: Settings) -> list[str]:
    """Host headers the API answers: the loopback names and the address it listens on. The API has no login, so this
    refuses a web page that points a domain of its own at 127.0.0.1 (DNS rebinding). On every address, any host."""
    if settings.host in ANY_ADDRESS:
        return ["*"]
    host = f"[{settings.host}]" if ":" in settings.host else settings.host  # an IPv6 Host header keeps its brackets
    return list(dict.fromkeys([*LOCAL_HOSTS, host]))


class Services:
    def __init__(self, settings: Settings, comfy_transport: httpx.AsyncBaseTransport | None):
        self.settings = settings
        self.db = Database(db_path(settings))
        self.comfy = ComfyClient(settings.comfy_url, transport=comfy_transport)
        self.launcher = ComfyLauncher(settings, self.comfy)
        self.queue = JobQueue(self.db, self.comfy, settings, RUNNERS, launcher=self.launcher)
        self._preflight: dict[str, preflight.FamilyStatus] | None = None
        self._preflight_at = 0.0
        self._preflight_lock = asyncio.Lock()
        self._animation: dict | None = None
        self._animation_at = 0.0
        self._animation_lock = asyncio.Lock()

    async def start(self) -> None:
        await self.queue.start()
        up = await self.comfy.is_up()
        if not up:
            log.warning("ComfyUI is not reachable at %s; jobs will fail until it runs", self.settings.comfy_url)
            return
        for family, status in (await self.preflight(up)).items():
            if status["ok"]:
                log.info("preflight %s: ok", family)
            else:
                log.warning("preflight %s: missing %s", family, status["missing_nodes"] + status["missing_models"])

    async def stop(self) -> None:
        await self.queue.stop()
        await self.comfy.aclose()
        self.db.close()

    async def preflight(self, comfy_up: bool) -> dict[str, dict]:
        if not comfy_up:
            down = preflight.FamilyStatus(ok=False, reason="comfyui_down")
            return {family: asdict(down) for family in preflight.REQUIRED}
        async with self._preflight_lock:
            stale = self._preflight is None or time.monotonic() - self._preflight_at > PREFLIGHT_TTL
            if stale or any(s.reason for s in self._preflight.values()):
                self._preflight = await preflight.check(self.comfy)
                self._preflight_at = time.monotonic()
            return {family: asdict(status) for family, status in self._preflight.items()}

    async def animation_status(self) -> dict:
        """sprite-gen and the codex login, checked again after PREFLIGHT_TTL, or at once while not ready."""
        async with self._animation_lock:
            stale = self._animation is None or time.monotonic() - self._animation_at > PREFLIGHT_TTL
            if stale or not self._animation["ok"]:
                self._animation = await animation_status(self.settings)
                self._animation_at = time.monotonic()
            return self._animation


def _services(request: Request) -> Services:
    return request.app.state.services


S = Annotated[Services, Depends(_services)]


def _project_or_404(s: Services, slug: str) -> Project:
    project = s.db.get_project(slug)
    if project is None:
        raise HTTPException(404, f"project {slug!r} not found")
    return project


def _job_out(s: Services, job: Job) -> JobOut:
    assets = [AssetOut.of(a) for a in s.db.list_assets(job_id=job.id)]
    return JobOut(**job.model_dump(), assets=assets)


def _current_job(s: Services) -> dict | None:
    job = s.db.get_job(s.queue.running_job_id) if s.queue.running_job_id else None
    if job is None:
        return None
    elapsed = (datetime.fromisoformat(now()) - datetime.fromisoformat(job.started_at)).total_seconds()
    return {"id": job.id, "project": job.project, "kind": job.kind, "stage": job.stage, "elapsed_s": round(elapsed)}


async def _load_reference(path: str):
    try:
        return await asyncio.to_thread(load_reference, path)
    except ReferenceImageError as e:
        raise HTTPException(422, str(e)) from e


def _export(s: Services, asset: Asset, body: ExportRequest) -> list[Path]:
    project = s.db.get_project(asset.project)
    dest = body.dest_dir or project.export_dir
    if not dest:
        raise HTTPException(400, "no export directory: pass dest_dir or set the project's export_dir")
    stem = export_stem(body.name or "") or f"{asset.kind}_{asset.project}_{asset.id}"
    if asset.kind == "animation":  # before EXPORT_FILES: a row, its JSON and a folder of frames, not one file
        paths = _export_animation(s, asset, Path(dest), stem)
    else:
        paths = _export_files(s, asset, Path(dest), stem)
    meta = dict(asset.meta)
    meta["exports"] = [*meta.get("exports", []), *({"path": str(p), "at": now()} for p in paths)]
    s.db.update_asset_meta(asset.id, meta)
    return paths


def _export_files(s: Services, asset: Asset, dest: Path, stem: str) -> list[Path]:
    group = next((g for g in EXPORT_FILES.get(asset.kind, ()) if g[0] in asset.files), ())
    sources = [from_rel(s.settings, asset.files[role]) for role in group if role in asset.files]
    missing = [str(p) for p in sources if not p.is_file()]
    if not sources or missing:
        raise HTTPException(404, f"nothing to export for asset {asset.id}: missing {missing or asset.kind}")
    paths = []
    try:
        dest.mkdir(parents=True, exist_ok=True)
        stem = unique_stem(dest, stem, [source.suffix for source in sources])  # one name for the WAV and OGG
        for source in sources:
            target = dest / f"{stem}{source.suffix}"
            shutil.copy2(source, target)
            paths.append(target)
    except OSError as e:
        raise HTTPException(400, f"could not export to {dest}: {e}") from e
    return paths


def _export_animation(s: Services, asset: Asset, dest: Path, stem: str) -> list[Path]:
    """<stem>.png (the frames in one row), <stem>.json (frame size and tags) and <stem>/000.png..., the way the game
    keeps a character's frames. One name for all three: if any of them is taken, all get _2."""
    frames = [from_rel(s.settings, rel) for rel in asset.meta.get("animation", {}).get("files", [])]
    sources = [from_rel(s.settings, asset.files[role]) for role in ("row", "json") if role in asset.files]
    missing = [str(p) for p in sources + frames if not p.is_file()]
    if len(sources) < 2 or not frames or missing:
        raise HTTPException(404, f"nothing to export for animation {asset.id}: missing {missing or 'its files'}")
    row, info_file = sources
    try:
        dest.mkdir(parents=True, exist_ok=True)
        stem = unique_stem(dest, stem, [".png", ".json", ""])  # "": the frames' folder
        info = json.loads(info_file.read_text(encoding="utf-8")) | {"name": stem, "image": f"{stem}.png"}
        folder = dest / stem
        folder.mkdir()
        for frame in frames:
            shutil.copy2(frame, folder / frame.name)
        shutil.copy2(row, dest / f"{stem}.png")
        (dest / f"{stem}.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    except OSError as e:
        raise HTTPException(400, f"could not export to {dest}: {e}") from e
    return [dest / f"{stem}.png", dest / f"{stem}.json", folder]


def create_app(settings: Settings, comfy_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services = Services(settings, comfy_transport)
        app.state.services = services
        await services.start()
        try:
            yield
        finally:
            await services.stop()

    app = FastAPI(title="AIAssetStudio", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts(settings))

    @app.get("/api/health")
    async def health() -> dict:
        """Cheap liveness check (does not touch ComfyUI); the MCP server uses it to see if the backend runs."""
        return {"backend": "ok"}

    @app.get("/api/status")
    async def status(s: S, ensure: bool = False) -> dict:
        """Backend, ComfyUI and queue state. `ensure=true` first starts ComfyUI if it is down (up to 2 min)."""
        comfy: dict = {"up": False, "url": s.settings.comfy_url}
        if ensure:
            try:
                await s.launcher.ensure()
            except ComfyUnavailable as e:
                comfy["error"] = str(e)
        try:
            stats = await s.comfy.system_stats(timeout=3.0)
        except ComfyError:
            stats = None
        if stats is not None:
            devices = stats.get("devices") or [{}]
            comfy |= {
                "up": True,
                "vram_free_mb": round(devices[0].get("vram_free", 0) / 2**20),
                "ram_free_mb": round(stats.get("system", {}).get("ram_free", 0) / 2**20),
            }
        return {
            "backend": "ok",
            "comfy": comfy,
            "preflight": await s.preflight(comfy["up"]),
            "animation": await s.animation_status(),
            "queue": {
                "running": s.queue.running_job_id,
                "queued": s.db.count_jobs("queued"),
                "current": _current_job(s),
            },
            "gallery_url": f"http://{s.settings.host}:{s.settings.port}/",
            "repo_dir": str(REPO_ROOT),  # for the gallery's MCP registration command
        }

    # --- projects -------------------------------------------------------------------------------

    @app.post("/api/projects", status_code=201)
    async def create_project(body: ProjectCreate, s: S) -> Project:
        """`reference_image` is copied into the studio; the original file is only read."""
        fields = body.model_dump(exclude={"reference_image"})
        reference = await _load_reference(body.reference_image) if body.reference_image else None
        try:
            project = s.db.create_project(**fields)
        except DuplicateSlug as e:
            raise HTTPException(409, str(e)) from e
        if reference is not None:
            stored = await asyncio.to_thread(store_reference, s.settings, project.slug, reference)
            project = s.db.update_project(project.slug, reference_image=stored)
        return project

    @app.get("/api/projects")
    async def list_projects(s: S) -> list[Project]:
        return s.db.list_projects()

    @app.get("/api/projects/{slug}")
    async def get_project(slug: str, s: S) -> Project:
        return _project_or_404(s, slug)

    @app.patch("/api/projects/{slug}")
    async def update_project(slug: str, body: ProjectUpdate, s: S) -> Project:
        project = _project_or_404(s, slug)
        fields = body.model_dump(exclude_unset=True)
        fields = {k: v for k, v in fields.items() if v is not None or k not in NOT_NULL_PROJECT_FIELDS}
        if missing := missing_pixel_fields(project.model_dump() | fields):
            raise HTTPException(422, f"a pixel_art project needs {', '.join(missing)}")
        if fields.get("reference_image"):
            reference = await _load_reference(fields["reference_image"])
            fields["reference_image"] = await asyncio.to_thread(store_reference, s.settings, slug, reference)
        return s.db.update_project(slug, **fields)

    @app.get("/api/projects/{slug}/reference")
    async def project_reference(slug: str, s: S) -> FileResponse:
        """The studio's copy of the project's reference image (enlarged if it was small pixel art)."""
        project = _project_or_404(s, slug)
        if not project.reference_image:
            raise HTTPException(404, f"project {slug!r} has no reference image")
        path = from_rel(s.settings, project.reference_image)
        if not path.is_file():
            raise HTTPException(404, f"file missing on disk: {project.reference_image}")
        return FileResponse(path)

    # --- jobs -----------------------------------------------------------------------------------

    @app.post("/api/jobs/image", status_code=202)
    async def create_image_job(body: ImageJobCreate, s: S) -> JobCreated:
        project = _project_or_404(s, body.project)
        params = body.model_dump(include={"kind", "description", "count", "seed"})
        job = s.db.create_job(project.id, "image", "qwen", params)
        s.queue.notify()
        return JobCreated(job_id=job.id)

    @app.post("/api/jobs/bgm", status_code=202)
    async def create_bgm_job(body: BgmJobCreate, s: S) -> JobCreated:
        """Instrumentals (ACE-Step) or, with vocal=true and lyrics, songs with vocals (YuE2)."""
        project = _project_or_404(s, body.project)
        params = body.model_dump(exclude={"project"})
        job = s.db.create_job(project.id, "bgm", "yue2" if body.vocal else "ace", params)
        s.queue.notify()
        return JobCreated(job_id=job.id)

    @app.post("/api/jobs/animation", status_code=202)
    async def create_animation_job(body: AnimationJobCreate, s: S) -> JobCreated:
        """Idle (4) + walk (6) frames of a sprite, made with sprite-gen and the codex CLI. A cloud job: it sends the
        sprite (enlarged), sprite-gen's layout guides and prompts to OpenAI, so only projects with animation_cloud on
        may ask for one."""
        project = _project_or_404(s, body.project)
        if not project.animation_cloud:
            raise HTTPException(
                422,
                f"project {project.slug!r} does not allow animations: they send its sprites to OpenAI (Codex CLI). "
                "Turn it on with update_project animation_cloud=true (PATCH the project with animation_cloud: true).",
            )
        if not project.pixel_art:
            raise HTTPException(422, "animations need a pixel-art project: its sprite size, feet row and colors")
        asset = s.db.get_asset(body.asset_id)
        if asset is None or asset.project_id != project.id:
            raise HTTPException(404, f"asset {body.asset_id!r} not found in project {project.slug!r}")
        if asset.kind != "sprite":
            raise HTTPException(422, f"asset {asset.id} is a {asset.kind}; animations start from a sprite")
        params = {"asset_id": asset.id, "count": body.count, "description": asset.meta.get("description", "")}
        job = s.db.create_job(project.id, "animation", "codex", params)
        s.queue.notify()
        return JobCreated(job_id=job.id)

    @app.get("/api/jobs")
    async def list_jobs(s: S, project: str | None = None, status: str | None = None) -> list[Job]:
        statuses = None
        if status:
            statuses = ["queued", "running"] if status == "active" else status.split(",")
            unknown = set(statuses) - set(get_args(JobStatus))
            if unknown:
                raise HTTPException(422, f"unknown status {sorted(unknown)}; use {list(get_args(JobStatus))} or active")
        if project is not None:
            _project_or_404(s, project)
        return s.db.list_jobs(project=project, statuses=statuses)

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str, s: S, wait: Annotated[float, Query(ge=0, le=60)] = 0) -> JobOut:
        """With `wait`, hold the request up to that many seconds until the job finishes (long polling)."""
        deadline = time.monotonic() + wait
        while True:
            job = s.db.get_job(job_id)
            if job is None:
                raise HTTPException(404, f"job {job_id!r} not found")
            remaining = deadline - time.monotonic()
            if job.status in TERMINAL_STATUSES or remaining <= 0:
                return _job_out(s, job)
            await asyncio.sleep(min(LONG_POLL_INTERVAL, remaining))

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str, s: S) -> JobOut:
        job = await s.queue.cancel(job_id)
        if job is None:
            raise HTTPException(404, f"job {job_id!r} not found")
        return _job_out(s, job)

    # --- assets ---------------------------------------------------------------------------------

    @app.get("/api/assets")
    async def list_assets(
        s: S,
        project: str | None = None,
        kind: Literal["sprite", "icon", "bgm", "animation"] | None = None,
        status: AssetStatus | None = None,
        job_id: str | None = None,
    ) -> list[AssetOut]:
        if project is not None:
            _project_or_404(s, project)
        return [AssetOut.of(a) for a in s.db.list_assets(project=project, kind=kind, status=status, job_id=job_id)]

    @app.get("/api/assets/{asset_id}")
    async def get_asset(asset_id: str, s: S) -> AssetOut:
        asset = s.db.get_asset(asset_id)
        if asset is None:
            raise HTTPException(404, f"asset {asset_id!r} not found")
        return AssetOut.of(asset)

    @app.patch("/api/assets/{asset_id}")
    async def update_asset(asset_id: str, body: AssetUpdate, s: S) -> AssetOut:
        asset = s.db.update_asset_status(asset_id, body.status)
        if asset is None:
            raise HTTPException(404, f"asset {asset_id!r} not found")
        return AssetOut.of(asset)

    @app.get("/api/assets/{asset_id}/files/{name}")
    async def asset_file(asset_id: str, name: str, s: S) -> FileResponse:
        asset = s.db.get_asset(asset_id)
        if asset is None:
            raise HTTPException(404, f"asset {asset_id!r} not found")
        if name not in asset.files:
            raise HTTPException(404, f"asset {asset_id!r} has no {name!r} file; available: {sorted(asset.files)}")
        path = from_rel(s.settings, asset.files[name])
        if not path.is_file():
            raise HTTPException(404, f"file missing on disk: {asset.files[name]}")
        return FileResponse(path, media_type=MEDIA_TYPES.get(path.suffix.lower()))

    @app.post("/api/assets/{asset_id}/export")
    async def export_asset(asset_id: str, body: ExportRequest, s: S) -> ExportResult:
        """Copy the processed file into `dest_dir` (or the project's export_dir): a song's WAV and OGG, an
        animation's row PNG, JSON and folder of frames. Never overwrites: adds _2, _3... to the name."""
        asset = s.db.get_asset(asset_id)
        if asset is None:
            raise HTTPException(404, f"asset {asset_id!r} not found")
        return ExportResult(paths=[str(p) for p in _export(s, asset, body)])

    # --- gallery (mounted last so /api, /docs and /openapi.json win) ----------------------------

    if GALLERY_DIST.is_dir():
        app.mount("/", StaticFiles(directory=GALLERY_DIST, html=True), name="gallery")
    else:

        @app.get("/", include_in_schema=False)
        async def gallery_not_built() -> HTMLResponse:
            return HTMLResponse(
                "<p>The gallery is not built. Run <code>npm --prefix web install</code> and "
                "<code>npm --prefix web run build</code>, then restart the backend. API docs: <a href='/docs'>/docs</a></p>"
            )

    return app
