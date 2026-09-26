import pytest
from fakes import ALL_MODELS, ALL_NODES, FakeComfy

import aiassetstudio.comfy.client as client_module
from aiassetstudio.cli import main
from aiassetstudio.comfy.graphs import VIGGLE_LORA


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
