import os
from pathlib import Path

import pytest

from aiassetstudio.config import _ENV, REPO_ROOT, Settings, find_codex_dir, is_loopback, load_settings


def test_defaults(monkeypatch):
    for var, _ in _ENV.values():
        monkeypatch.delenv(var, raising=False)
    s = load_settings()
    assert s == Settings()
    assert s.host == "127.0.0.1"
    assert s.port == 8765
    assert s.data_dir == REPO_ROOT / "data"
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert s.comfy_url == "http://127.0.0.1:8188"
    assert s.comfy_dir == REPO_ROOT.parent / "ComfyUI"  # next to this repository
    assert s.comfy_python == ""
    assert s.idle_free_seconds == 60
    assert s.image_timeout == 300
    assert s.bgm_timeout == 600
    assert s.ffmpeg == "ffmpeg"
    assert Path(s.sprite_gen) == REPO_ROOT.parent / "sprite-gen" / ".venv" / "Scripts" / "sprite-gen.exe"
    assert s.codex_dir == ""
    assert s.animation_timeout == 900


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("AIAS_HOST", "127.0.0.2")
    monkeypatch.setenv("AIAS_PORT", "9000")
    monkeypatch.setenv("AIAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AIAS_COMFY_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("AIAS_COMFY_DIR", str(tmp_path / "comfy"))
    monkeypatch.setenv("AIAS_COMFY_PYTHON", "D:/portable/python_embeded/python.exe")
    monkeypatch.setenv("AIAS_IDLE_FREE_SECONDS", "0.5")
    monkeypatch.setenv("AIAS_IMAGE_TIMEOUT", "12")
    monkeypatch.setenv("AIAS_BGM_TIMEOUT", "34")
    monkeypatch.setenv("AIAS_FFMPEG", "D:/tools/ffmpeg.exe")
    monkeypatch.setenv("AIAS_SPRITE_GEN", "D:/sg/sprite-gen.exe")
    monkeypatch.setenv("AIAS_CODEX_DIR", "D:/codex")
    monkeypatch.setenv("AIAS_ANIMATION_TIMEOUT", "56")
    s = load_settings()
    assert s.host == "127.0.0.2"
    assert s.port == 9000
    assert s.data_dir == Path(tmp_path)
    assert s.comfy_url == "http://127.0.0.1:9999"
    assert s.comfy_dir == tmp_path / "comfy"
    assert s.comfy_python == "D:/portable/python_embeded/python.exe"
    assert s.idle_free_seconds == 0.5
    assert s.image_timeout == 12
    assert s.bgm_timeout == 34
    assert s.ffmpeg == "D:/tools/ffmpeg.exe"
    assert s.sprite_gen == "D:/sg/sprite-gen.exe"
    assert s.codex_dir == "D:/codex"
    assert s.animation_timeout == 56


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1", True),
        ("127.0.0.2", True),
        ("localhost", True),
        ("::1", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.168.0.10", False),
        ("studio.lan", False),
    ],
)
def test_is_loopback(host, loopback):
    assert is_loopback(host) is loopback


def _codex(root: Path, name: str, mtime: float) -> Path:
    exe = root / "OpenAI" / "Codex" / "bin" / name / "codex.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    os.utime(exe, (mtime, mtime))
    return exe.parent


def test_find_codex_dir_takes_the_newest_app_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    _codex(tmp_path, "old", 1_000_000)
    newest = _codex(tmp_path, "new", 2_000_000)
    assert find_codex_dir(Settings()) == newest


def test_find_codex_dir_prefers_the_setting(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    _codex(tmp_path, "app", 1_000_000)
    assert find_codex_dir(Settings(codex_dir="D:/codex")) == Path("D:/codex")


def test_find_codex_dir_leaves_path_when_nothing_is_installed(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert find_codex_dir(Settings()) is None
    monkeypatch.delenv("LOCALAPPDATA")
    assert find_codex_dir(Settings()) is None
