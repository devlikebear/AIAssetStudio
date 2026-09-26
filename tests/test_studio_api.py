import httpx
import pytest

from aiassetstudio.api.app import create_app
from aiassetstudio.config import Settings
from aiassetstudio.mcp_bridge.studio_api import BackendError, StudioApi


@pytest.fixture
async def api(settings, fake_comfy):
    """StudioApi wired to the Phase 1 app in-process (no port), with its lifespan running."""
    app = create_app(settings, comfy_transport=fake_comfy.transport)
    async with app.router.lifespan_context(app):
        client = StudioApi("http://127.0.0.1:8765", transport=httpx.ASGITransport(app=app))
        yield client
        await client.aclose()


async def test_round_trip(api, tmp_path):
    await api.ensure_backend()  # already up: returns without starting anything
    assert (await api.status())["backend"] == "ok"
    project = await api.create_project("demo", "Demo", style="cute chibi")
    assert project["style"] == "cute chibi"
    assert [p["slug"] for p in await api.list_projects()] == ["demo"]
    assert (await api.update_project("demo", export_dir=str(tmp_path / "out")))["export_dir"] == str(tmp_path / "out")

    job_id = await api.create_image_job("demo", "sprite", "a slime", count=2)
    job = await api.get_job(job_id, wait=10)
    assert job["status"] == "done" and len(job["assets"]) == 2
    asset = job["assets"][0]
    assert (await api.get_file(asset["id"], "preview")).startswith(b"\x89PNG")
    assert (await api.set_asset_status(asset["id"], "selected"))["status"] == "selected"
    assert [a["id"] for a in await api.list_assets(project="demo", status="selected")] == [asset["id"]]
    [path] = await api.export_asset(asset["id"])
    assert path.startswith(str(tmp_path / "out"))
    assert (await api.cancel_job(job_id))["status"] == "done"


async def test_errors_carry_the_backend_message(api):
    with pytest.raises(BackendError, match="HTTP 404: project 'nope' not found"):
        await api.get_project("nope")
    await api.create_project("demo", "Demo")
    with pytest.raises(BackendError, match="HTTP 422: kind"):
        await api.create_image_job("demo", "tileset", "x")


class Backend:
    """A transport that refuses connections until the fake spawn "starts" the backend."""

    def __init__(self, starts: bool = True):
        self.up = False
        self.starts = starts
        self.spawned: list[list[str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if not self.up:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"backend": "ok"})

    def spawn(self, args, **kwargs):
        self.spawned.append(args)
        assert kwargs["log_path"] is not None  # output to the log, never to the MCP stdio channel
        self.up = self.starts


async def test_ensure_backend_starts_it(tmp_path):
    backend = Backend()
    api = StudioApi(
        "http://studio.test",
        transport=httpx.MockTransport(backend.handler),
        log_path=tmp_path / "logs" / "backend.log",
        spawn=backend.spawn,
        interval=0.01,
    )
    await api.ensure_backend()
    await api.ensure_backend()
    [args] = backend.spawned
    assert args[1:] == ["-m", "aiassetstudio", "serve"]
    await api.aclose()


def test_from_settings_puts_the_address_on_the_command_line(tmp_path):
    settings = Settings(port=8766, data_dir=tmp_path / "data")
    api = StudioApi.from_settings(settings)
    assert api.serve_args == ["serve", "--host", "127.0.0.1", "--port", "8766", "--data-dir", str(tmp_path / "data")]
    assert api.log_path == tmp_path / "data" / "logs" / "backend.log"


async def test_ensure_backend_reports_an_older_backend(tmp_path):
    # A Phase 1 backend has no /api/health: say so at once instead of starting a second one that cannot bind.
    spawned = []
    api = StudioApi(
        "http://studio.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(404, json={"detail": "Not Found"})),
        log_path=tmp_path / "backend.log",
        spawn=lambda *args, **kwargs: spawned.append(args),
    )
    with pytest.raises(BackendError, match="older backend"):
        await api.ensure_backend()
    assert spawned == []
    await api.aclose()


async def test_ensure_backend_gives_up_with_log_path(tmp_path):
    backend = Backend(starts=False)
    log_path = tmp_path / "logs" / "backend.log"
    api = StudioApi(
        "http://studio.test",
        transport=httpx.MockTransport(backend.handler),
        log_path=log_path,
        spawn=backend.spawn,
        start_timeout=0.05,
        interval=0.01,
    )
    with pytest.raises(BackendError, match="did not start") as exc:
        await api.ensure_backend()
    assert str(log_path) in str(exc.value)
    await api.aclose()
