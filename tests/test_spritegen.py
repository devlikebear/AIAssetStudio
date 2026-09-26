import asyncio
import ctypes
import json
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

from aiassetstudio.config import Settings
from aiassetstudio.spritegen.access import animation_status, codex_command
from aiassetstudio.spritegen.client import SpriteGen, SpriteGenError, last_json

FAKE = Path(__file__).parent / "fake_spritegen.py"
STATES = {
    "idle": {"frames": 4, "fps": 5, "loop": True, "action": "subtle breathing"},
    "frontwalk": {"frames": 6, "fps": 10, "loop": True, "action": "walk toward the viewer"},
}


@pytest.fixture
def log(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_SPRITEGEN_LOG", str(path))
    for var in ("FAKE_SPRITEGEN_FAIL", "FAKE_SPRITEGEN_SLOW", "FAKE_SPRITEGEN_HEIGHTS"):
        monkeypatch.delenv(var, raising=False)
    return path


def calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def make_base(path: Path) -> Path:
    sprite = Image.new("RGBA", (32, 32))
    sprite.paste((20, 20, 30, 255), (8, 3, 25, 29))  # 17x26 like LAST LIGHT's shadow enemy
    sprite.resize((1024, 1024), Image.Resampling.NEAREST).save(path)
    return path


def test_last_json():
    assert last_json('progress 1/2\n{\n  "ok": true,\n  "cell": {\n    "w": 1\n  }\n}\n') == {
        "ok": True,
        "cell": {"w": 1},
    }
    assert last_json('{"a": 1}\n{\n  "ok": false\n}') == {"ok": False}
    # gen-set: JSON lines, then a table
    assert last_json('{"state": "idle", "ok": true}\n| state | seconds |\n|---|---|\n') is None
    assert last_json("") is None


async def test_prepare_generate_extract_compose(tmp_path, log):
    sg = SpriteGen([sys.executable, str(FAKE)], codex_dir=tmp_path / "codex-app")
    run = tmp_path / "run"
    base = make_base(tmp_path / "base.png")
    report = await sg.prepare(run, base, (32, 32), 12, "a shadow", STATES, character_id="asset-1", safe_margin=3)
    assert report["states"] == ["idle", "frontwalk"]
    request = json.loads((run / "sprite-request.json").read_text(encoding="utf-8"))
    assert request["cell"] == {"width": 32, "height": 32, "safe_margin": 3}
    assert request["states"] == STATES
    assert "--fit-pixel-unfake" in request["flags"] and "--fit-ground-frames" in request["flags"]

    genset = await sg.gen_set(run)
    assert (genset["ok"], genset["failed"]) == (2, [])
    assert {c["tool"] for c in calls(log)} == {"prepare", "gen-set"}
    gen_call = next(c for c in calls(log) if c["tool"] == "gen-set")
    assert gen_call["args"][gen_call["args"].index("--provider") + 1] == "codex"
    assert gen_call["path"].split(os.pathsep)[0] == str(tmp_path / "codex-app")  # the app's codex comes first

    extracted = await sg.extract(run)
    assert extracted["ok"] is True
    assert any("exceeds the physical cap" in w for w in extracted["warnings"])  # the fake draws 34-38 > 29
    composed = await sg.compose(run)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert Path(composed["atlas"]) == run / "sprite-sheet-alpha.png"
    assert [len(manifest["frame_layout"]["rows"][s]) for s in STATES] == [4, 6]
    assert (await sg.inspect(run))["ok"] is True


async def test_failed_stage_raises_with_its_errors(tmp_path, log, monkeypatch):
    sg = SpriteGen([sys.executable, str(FAKE)])
    monkeypatch.setenv("FAKE_SPRITEGEN_FAIL", "prepare")
    with pytest.raises(SpriteGenError, match="sprite-gen prepare failed \\(exit 1\\): fake prepare failure") as e:
        await sg.prepare(tmp_path / "run", make_base(tmp_path / "base.png"), (32, 32), 12, "x", STATES)
    assert e.value.report["ok"] is False


async def test_failed_rows_raise_with_the_reasons(tmp_path, log, monkeypatch):
    sg = SpriteGen([sys.executable, str(FAKE)])
    run = tmp_path / "run"
    await sg.prepare(run, make_base(tmp_path / "base.png"), (32, 32), 12, "x", STATES)
    monkeypatch.setenv("FAKE_SPRITEGEN_FAIL", "gen-set")
    with pytest.raises(SpriteGenError, match="idle: gen exited 1; codex: not logged in") as e:
        await sg.gen_set(run)
    assert e.value.report["failed"] == ["idle", "frontwalk"]


async def test_inspect_failure_is_returned(tmp_path, log, monkeypatch):
    monkeypatch.setenv("FAKE_SPRITEGEN_FAIL", "inspect")
    report = await SpriteGen([sys.executable, str(FAKE)]).inspect(tmp_path)
    assert report == {"ok": False, "errors": ["fake inspect failure"], "warnings": []}


async def test_missing_program(tmp_path):
    with pytest.raises(SpriteGenError, match="cannot run sprite-gen .*AIAS_SPRITE_GEN"):
        await SpriteGen([str(tmp_path / "nope.exe")]).extract(tmp_path)


def _alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


async def test_cancel_kills_the_stage(tmp_path, log, monkeypatch):
    monkeypatch.setenv("FAKE_SPRITEGEN_SLOW", "extract:30")
    task = asyncio.create_task(SpriteGen([sys.executable, str(FAKE)]).extract(tmp_path))
    async with asyncio.timeout(10):
        while not calls(log):
            await asyncio.sleep(0.05)
    pid = calls(log)[0]["pid"]
    assert _alive(pid)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not _alive(pid)


async def test_stage_time_limit(tmp_path, log, monkeypatch):
    monkeypatch.setenv("FAKE_SPRITEGEN_SLOW", "extract:30")
    with pytest.raises(SpriteGenError, match="took longer than 0.5 s"):
        await SpriteGen([sys.executable, str(FAKE)], timeout=0.5).extract(tmp_path)


def test_from_settings_and_version(tmp_path):
    sg = SpriteGen.from_settings(Settings(sprite_gen=str(FAKE), codex_dir=str(tmp_path)))
    assert sg.cmd == [sys.executable, str(FAKE)]  # a .py runs on this Python
    assert sg.codex_dir == tmp_path
    assert sg.version() is None
    venv = tmp_path / "sg" / ".venv"
    (venv / "Lib" / "site-packages" / "sprite_gen-2.9.0.dist-info").mkdir(parents=True)
    installed = SpriteGen.from_settings(Settings(sprite_gen=str(venv / "Scripts" / "sprite-gen.exe")))
    assert installed.cmd == [str(venv / "Scripts" / "sprite-gen.exe")]
    assert installed.version() == "2.9.0"


FAKE_CODEX = """import os, sys
if os.environ.get("FAKE_CODEX_LOGIN") == "out":
    print("Not logged in", file=sys.stderr)
    sys.exit(1)
print("Logged in using ChatGPT", file=sys.stderr)
"""


@pytest.fixture
def codex_dir(tmp_path) -> Path:
    folder = tmp_path / "codex-app"
    folder.mkdir()
    (folder / "codex.py").write_text(FAKE_CODEX, encoding="utf-8")
    return folder


async def test_animation_status_ready(codex_dir, monkeypatch):
    monkeypatch.delenv("FAKE_CODEX_LOGIN", raising=False)
    settings = Settings(sprite_gen=str(FAKE), codex_dir=str(codex_dir))
    assert codex_command(settings) == [sys.executable, str(codex_dir / "codex.py")]
    status = await animation_status(settings)
    assert status == {
        "ok": True,
        "reason": None,
        "sprite_gen": str(FAKE),
        "codex": str(codex_dir / "codex.py"),
        "login": "ready",
    }


async def test_animation_status_not_logged_in(codex_dir, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_LOGIN", "out")
    status = await animation_status(Settings(sprite_gen=str(FAKE), codex_dir=str(codex_dir)))
    assert (status["ok"], status["login"]) == (False, "Not logged in")
    assert status["reason"] == "codex is not logged in (Not logged in); run `codex login` and sign in with ChatGPT"


async def test_animation_status_missing(tmp_path):
    status = await animation_status(Settings(sprite_gen=str(tmp_path / "sg.exe"), codex_dir=str(tmp_path)))
    assert (status["ok"], status["login"], status["codex"], status["sprite_gen"]) == (False, "missing", None, None)
    assert status["reason"].startswith("sprite-gen not found at ")
    assert "codex CLI not found (install the Codex app, or set AIAS_CODEX_DIR)" in status["reason"]
