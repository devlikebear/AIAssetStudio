import json

import pytest
from fakes import ALL_MODELS, ALL_NODES, FakeComfy

import aiassetstudio.comfy.client as client_module
from aiassetstudio import cli
from aiassetstudio.cli import main
from aiassetstudio.comfy.graphs import VIGGLE_LORA
from aiassetstudio.mcp_bridge.studio_api import BackendError, StudioApi
from aiassetstudio.store.db import SCHEMA_VERSION


def run_check(monkeypatch, fake: FakeComfy) -> int:
    real = client_module.ComfyClient
    monkeypatch.setattr(client_module, "ComfyClient", lambda url: real(url, transport=fake.transport))
    with pytest.raises(SystemExit) as exc:
        main(["check"])
    return exc.value.code


def test_check_ok(monkeypatch, capsys):
    assert run_check(monkeypatch, FakeComfy()) == 0
    out = capsys.readouterr().out
    assert "ComfyUI: up" in out and "version 0.37.0" in out
    assert "qwen: ok" in out


def test_check_names_what_is_missing(monkeypatch, capsys):
    models = {k: set(v) for k, v in ALL_MODELS.items()}
    models["loras"].discard(VIGGLE_LORA)
    fake = FakeComfy(nodes=ALL_NODES - {"ViggleTurboSigmas"}, models=models)
    assert run_check(monkeypatch, fake) == 1
    out = capsys.readouterr().out
    assert "qwen: not ready" in out
    assert "missing node:  ViggleTurboSigmas" in out
    assert f"missing model: loras/{VIGGLE_LORA}" in out


def test_serve_warns_when_reachable_from_other_machines(monkeypatch, caplog, tmp_path):
    import uvicorn

    runs = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: runs.append(kwargs))
    for host, warned in (("127.0.0.1", False), ("0.0.0.0", True)):
        caplog.clear()
        with pytest.raises(SystemExit) as exc:
            main(["serve", "--host", host, "--port", "8799", "--data-dir", str(tmp_path / "data")])
        assert exc.value.code == 0
        assert ("the API has no login" in caplog.text) is warned, host
    assert [run["host"] for run in runs] == ["127.0.0.1", "0.0.0.0"]


def test_check_comfyui_down(monkeypatch, capsys):
    assert run_check(monkeypatch, FakeComfy(down=True)) == 1
    out = capsys.readouterr().out
    assert "ComfyUI: down" in out
    assert "qwen: not ready (comfyui_down)" in out


class FakeApi:
    """StudioApi as the `pack` command sees it."""

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def ensure_backend(self):
        pass

    async def aclose(self):
        pass

    def _answer(self, name, *args):
        self.calls.append((name, *args))
        if self.error:
            raise self.error
        return {"id": "speech-ko", "status": "installing", "stage": "downloading 1/2", "error": None}

    async def install_pack(self, pack_id):
        return self._answer("install", pack_id)

    async def get_pack(self, pack_id):
        return self._answer("status", pack_id)

    async def cancel_pack(self, pack_id):
        return self._answer("cancel", pack_id)

    async def remove_pack(self, pack_id):
        return self._answer("remove", pack_id)

    async def list_packs(self):
        return [self._answer("list")]


def run_pack(monkeypatch, api, *args) -> int:
    seen = []

    def from_settings(settings, client=None):
        seen.append(client)
        return api

    monkeypatch.setattr(StudioApi, "from_settings", from_settings)
    with pytest.raises(SystemExit) as e:
        main(["pack", *args])
    assert seen == ["cli"]
    return e.value.code


def test_pack_install_returns_at_once_with_the_state(monkeypatch, capsys):
    api = FakeApi()
    assert run_pack(monkeypatch, api, "install", "speech-ko") == 0
    assert api.calls == [("install", "speech-ko")]
    assert "speech-ko: installing (downloading 1/2)" in capsys.readouterr().out


def test_pack_install_without_consent_exits_3_with_the_gallery_url(monkeypatch, capsys):
    detail = {"code": "consent_required", "message": "needs consent", "gallery_url": "http://x/#/packs/speech-ko"}
    assert run_pack(monkeypatch, FakeApi(BackendError("HTTP 409", detail)), "install", "speech-ko") == 3
    assert "http://x/#/packs/speech-ko" in capsys.readouterr().out


def test_pack_install_json_gives_the_url_to_an_agent(monkeypatch, capsys):
    detail = {"code": "consent_required", "message": "m", "gallery_url": "http://x/#/packs/speech-ko"}
    assert run_pack(monkeypatch, FakeApi(BackendError("HTTP 409", detail)), "install", "speech-ko", "--json") == 3
    assert json.loads(capsys.readouterr().out)["gallery_url"].endswith("speech-ko")


def test_pack_other_errors_exit_1(monkeypatch, capsys):
    assert run_pack(monkeypatch, FakeApi(BackendError("HTTP 507: no disk")), "install", "speech-ko") == 1
    assert "no disk" in capsys.readouterr().err


@pytest.mark.parametrize("action", ["status", "cancel", "remove"])
def test_pack_actions(monkeypatch, action):
    api = FakeApi()
    assert run_pack(monkeypatch, api, action, "speech-ko", "--json") == 0
    assert api.calls == [(action, "speech-ko")]


def test_pack_list(monkeypatch, capsys):
    assert run_pack(monkeypatch, FakeApi(), "list") == 0
    assert "speech-ko" in capsys.readouterr().out


def test_there_is_no_accept_command():
    with pytest.raises(SystemExit) as e:
        main(["pack", "accept", "speech-ko"])
    assert e.value.code == 2


def test_setup_twice_gives_the_same_report_and_downloads_nothing(monkeypatch, capsys, tmp_path):
    async def ensure(settings):
        pass

    monkeypatch.setenv("AIAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(cli, "_ensure_backend", ensure)
    outputs = []
    for _ in range(2):
        with pytest.raises(SystemExit) as e:
            main(["setup", "--json"])
        assert e.value.code == 0
        outputs.append(capsys.readouterr().out)
    assert outputs[0] == outputs[1]
    report = json.loads(outputs[0])
    assert report["backend"] is True
    assert report["schema_version"] == SCHEMA_VERSION
    assert sorted(p.name for p in (tmp_path / "data").iterdir() if p.is_dir()) == []


def test_setup_reports_a_backend_that_will_not_start(monkeypatch, capsys, tmp_path):
    async def ensure(settings):
        raise BackendError("did not start")

    monkeypatch.setenv("AIAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(cli, "_ensure_backend", ensure)
    with pytest.raises(SystemExit) as e:
        main(["setup"])
    assert e.value.code == 1
    assert "did not start" in capsys.readouterr().out


def test_serve_detach_prints_the_gallery(monkeypatch, capsys, tmp_path):
    started = []

    async def ensure(settings):
        started.append(settings.port)

    monkeypatch.setattr(cli, "_ensure_backend", ensure)
    with pytest.raises(SystemExit) as e:
        main(["serve", "--detach", "--port", "8799", "--data-dir", str(tmp_path / "data")])
    assert e.value.code == 0
    assert started == [8799]
    assert "8799" in capsys.readouterr().out
