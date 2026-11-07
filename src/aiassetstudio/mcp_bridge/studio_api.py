"""HTTP client for the backend, used by the MCP server. Starts the backend when it is not running."""

import asyncio
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx

from ..config import REPO_ROOT, Settings
from ..detach import spawn_detached
from ..store.files import logs_dir

log = logging.getLogger(__name__)

CLIENT_HEADER = "X-Studio-Client"
HEALTH_TIMEOUT = 5.0
START_TIMEOUT = 30.0


class BackendError(Exception):
    """The backend refused a request, or could not be reached or started. The message is meant for the user. `detail`
    is the backend's own answer when it says more than a sentence, such as a consent request's gallery URL."""

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail or {}


def _error_detail(r: httpx.Response) -> object:
    try:
        return r.json().get("detail", r.text)
    except ValueError:
        return r.text


def _error_message(r: httpx.Response) -> str:
    detail = _error_detail(r)
    if isinstance(detail, dict):
        detail = detail.get("message", detail)
    if isinstance(detail, list):  # FastAPI validation errors
        detail = "; ".join(f"{'.'.join(str(p) for p in d.get('loc', [])[1:])}: {d.get('msg')}" for d in detail)
    return f"HTTP {r.status_code}: {detail}"


class StudioApi:
    def __init__(
        self,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        log_path: Path | None = None,
        serve_args: Sequence[str] = ("serve",),
        spawn: Callable[..., object] = spawn_detached,
        start_timeout: float = START_TIMEOUT,
        interval: float = 0.5,
        client: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.log_path = log_path
        self.serve_args = list(serve_args)
        self.spawn = spawn
        self.start_timeout = start_timeout
        self.interval = interval
        # The MCP server passes no client: the API refuses it what only a person or the CLI may do.
        headers = {CLIENT_HEADER: client} if client else {}
        self._http = httpx.AsyncClient(
            base_url=self.base_url, transport=transport, timeout=httpx.Timeout(30.0, connect=5.0), headers=headers
        )
        self._lock = asyncio.Lock()

    @classmethod
    def from_settings(cls, settings: Settings, client: str | None = None) -> "StudioApi":
        # Host, port and data folder on the command line, not only in the environment: the stop command in the README
        # and the smoke scripts find a backend by its command line.
        serve = ["serve", "--host", settings.host, "--port", str(settings.port), "--data-dir", str(settings.data_dir)]
        return cls(
            f"http://{settings.host}:{settings.port}",
            log_path=logs_dir(settings) / "backend.log",
            serve_args=serve,
            client=client,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- backend process ------------------------------------------------------------------------

    async def ensure_backend(self) -> None:
        """Return once the backend answers, starting it first if needed. Raises BackendError on failure."""
        if await self._healthy():
            return
        async with self._lock:
            if await self._healthy():
                return
            await asyncio.to_thread(self._spawn_backend)  # the WMI call takes about a second
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.start_timeout
            while loop.time() < deadline:
                await asyncio.sleep(self.interval)
                if await self._healthy():
                    return
            raise BackendError(f"the backend did not start within {self.start_timeout:g} s; see {self.log_path}")

    async def _healthy(self) -> bool:
        try:
            r = await self._http.get("/api/health", timeout=HEALTH_TIMEOUT)
        except httpx.TransportError:
            return False
        if r.status_code != 200:
            # Something answers on the port but not as this version: starting another backend would only clash.
            raise BackendError(
                f"{self.base_url} answers /api/health with HTTP {r.status_code}. An older backend is probably "
                "running there; stop it (Ctrl+C in its terminal) and try again."
            )
        return True

    def _spawn_backend(self) -> None:
        # Outside this MCP server and its Claude Code session (aiassetstudio.detach), so the backend keeps serving
        # every session after this one closes. If two sessions start it at once, the second backend exits on the
        # port clash; the health check still passes. Its output goes to the log, never to the MCP stdio channel.
        log.info("starting the backend (log: %s)", self.log_path)
        self.spawn([sys.executable, "-m", "aiassetstudio", *self.serve_args], cwd=REPO_ROOT, log_path=self.log_path)

    # --- REST -----------------------------------------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            r = await self._http.request(method, path, **kwargs)
        except httpx.TransportError as e:
            raise BackendError(f"backend not reachable at {self.base_url}: {e!r}") from e
        if r.status_code >= 400:
            detail = _error_detail(r)
            raise BackendError(_error_message(r), detail if isinstance(detail, dict) else None)
        return r

    async def status(self) -> dict:
        return (await self._request("GET", "/api/status")).json()

    async def list_projects(self) -> list[dict]:
        return (await self._request("GET", "/api/projects")).json()

    async def get_project(self, slug: str) -> dict:
        return (await self._request("GET", f"/api/projects/{slug}")).json()

    async def create_project(
        self, slug: str, name: str, style: str = "", export_dir: str | None = None, **spec
    ) -> dict:
        """`spec`: pixel_art, logical_width, logical_height, icon_size, max_colors, palette, reference_image."""
        body = {"slug": slug, "name": name, "style": style, "export_dir": export_dir}
        body |= {k: v for k, v in spec.items() if v is not None}
        return (await self._request("POST", "/api/projects", json=body)).json()

    async def update_project(self, slug: str, **fields) -> dict:
        return (await self._request("PATCH", f"/api/projects/{slug}", json=fields)).json()

    async def create_image_job(
        self, project: str, kind: str, description: str, count: int = 4, seed: int | None = None
    ) -> str:
        body = {"project": project, "kind": kind, "description": description, "count": count, "seed": seed}
        return (await self._request("POST", "/api/jobs/image", json=body)).json()["job_id"]

    async def create_bgm_job(self, project: str, brief: str, bpm: int, **options) -> str:
        """`options`: seconds, loop, vocal, lyrics, keyscale, count, seed (None = the API's default)."""
        body = {"project": project, "brief": brief, "bpm": bpm} | {k: v for k, v in options.items() if v is not None}
        return (await self._request("POST", "/api/jobs/bgm", json=body)).json()["job_id"]

    async def create_animation_job(self, asset_id: str, count: int = 1) -> str:
        """An animation of a sprite asset, in the sprite's own project."""
        asset = (await self._request("GET", f"/api/assets/{asset_id}")).json()
        body = {"project": asset["project"], "asset_id": asset_id, "count": count}
        return (await self._request("POST", "/api/jobs/animation", json=body)).json()["job_id"]

    async def get_job(self, job_id: str, wait: float = 0) -> dict:
        r = await self._request("GET", f"/api/jobs/{job_id}", params={"wait": wait}, timeout=wait + 30)
        return r.json()

    async def list_assets(
        self, project: str | None = None, kind: str | None = None, status: str | None = None, job_id: str | None = None
    ) -> list[dict]:
        params = {k: v for k, v in {"project": project, "kind": kind, "status": status, "job_id": job_id}.items() if v}
        return (await self._request("GET", "/api/assets", params=params)).json()

    async def set_asset_status(self, asset_id: str, status: str) -> dict:
        return (await self._request("PATCH", f"/api/assets/{asset_id}", json={"status": status})).json()

    async def export_asset(self, asset_id: str, dest_dir: str | None = None, name: str | None = None) -> list[str]:
        body = {"dest_dir": dest_dir, "name": name}
        return (await self._request("POST", f"/api/assets/{asset_id}/export", json=body)).json()["paths"]

    async def cancel_job(self, job_id: str) -> dict:
        return (await self._request("POST", f"/api/jobs/{job_id}/cancel")).json()

    async def get_file(self, asset_id: str, name: str) -> bytes:
        return (await self._request("GET", f"/api/assets/{asset_id}/files/{name}")).content

    async def create_book(self, project: str, title: str, source: dict | None, **size) -> dict:
        body = {"project": project, "title": title, "source": source}
        return (await self._request("POST", "/api/books", json=body | {k: v for k, v in size.items() if v})).json()

    async def get_book(self, book_id: str) -> dict:
        return (await self._request("GET", f"/api/books/{book_id}")).json()

    async def update_book(self, book_id: str, **fields) -> dict:
        return (await self._request("PATCH", f"/api/books/{book_id}", json=fields)).json()

    async def save_pages(self, book_id: str, pages: list[dict]) -> dict:
        return (await self._request("PUT", f"/api/books/{book_id}/pages", json=pages)).json()

    async def save_sheets(self, book_id: str, sheets: list[dict]) -> dict:
        return (await self._request("PUT", f"/api/books/{book_id}/sheets", json=sheets)).json()

    async def set_terms(self, book_id: str, terms: list[dict]) -> list[dict]:
        return (await self._request("PUT", f"/api/books/{book_id}/terms", json=terms)).json()

    async def generate_pages(self, book_id: str, pages: list[int] | None, seed: int | None) -> list[str]:
        body = {"pages": pages, "seed": seed}
        return (await self._request("POST", f"/api/books/{book_id}/generate", json=body)).json()["job_ids"]

    async def generate_sheet(self, sheet_id: str, seed: int | None) -> str:
        r = await self._request("POST", f"/api/sheets/{sheet_id}/generate", json={"seed": seed})
        return r.json()["job_id"]

    async def update_page(self, page_id: str, **fields) -> dict:
        return (await self._request("PATCH", f"/api/pages/{page_id}", json=fields)).json()

    async def check_sources(self, book_id: str, versions: dict[str, int]) -> list[dict]:
        r = await self._request("POST", f"/api/books/{book_id}/check-sources", json={"versions": versions})
        return r.json()

    async def export_book(self, book_id: str, allow_draft: bool, format: str = "pdf") -> str:
        body = {"allow_draft": allow_draft, "format": format}
        return (await self._request("POST", f"/api/books/{book_id}/export", json=body)).json()["job_id"]

    async def narrate_pages(self, book_id: str, pages: list[int] | None, seed: int | None) -> list[str]:
        body = {"pages": pages, "seed": seed}
        return (await self._request("POST", f"/api/books/{book_id}/narrate", json=body)).json()["job_ids"]

    async def generate_clips(
        self, book_id: str, pages: list[int] | None, seed: int | None, model: str = "ltx", seconds: float = 5
    ) -> list[str]:
        body = {"pages": pages, "seed": seed, "model": model, "seconds": seconds}
        return (await self._request("POST", f"/api/books/{book_id}/clips", json=body)).json()["job_ids"]

    async def list_packs(self) -> list[dict]:
        return (await self._request("GET", "/api/packs")).json()

    async def get_pack(self, pack_id: str) -> dict:
        return (await self._request("GET", f"/api/packs/{pack_id}")).json()

    async def install_pack(self, pack_id: str) -> dict:
        return (await self._request("POST", f"/api/packs/{pack_id}/install")).json()

    async def cancel_pack(self, pack_id: str) -> dict:
        return (await self._request("POST", f"/api/packs/{pack_id}/cancel")).json()

    async def remove_pack(self, pack_id: str) -> dict:
        return (await self._request("DELETE", f"/api/packs/{pack_id}")).json()
