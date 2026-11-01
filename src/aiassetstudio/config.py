"""Backend settings, read from AIAS_* environment variables with defaults."""

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# ComfyUI and sprite-gen are looked for in folders next to this repository unless AIAS_COMFY_DIR / AIAS_SPRITE_GEN
# say otherwise.
SIBLING_DIR = REPO_ROOT.parent


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = REPO_ROOT / "data"
    comfy_url: str = "http://127.0.0.1:8188"
    comfy_dir: Path = SIBLING_DIR / "ComfyUI"  # used by the Phase 2 auto-launcher
    comfy_python: str = ""  # ComfyUI's Python for the auto-launcher; empty = <comfy_dir>\.venv\Scripts\python.exe
    idle_free_seconds: float = 60
    image_timeout: float = 300  # seconds
    bgm_timeout: float = 600  # seconds
    ffmpeg: str = "ffmpeg"  # for the BGM's OGG copy
    sprite_gen: str = str(SIBLING_DIR / "sprite-gen" / ".venv" / "Scripts" / "sprite-gen.exe")  # animations (own venv)
    codex_dir: str = ""  # folder of the codex CLI for sprite-gen; empty = find_codex_dir's search
    animation_timeout: float = 900  # seconds
    book_font: str = r"C:\Windows\Fonts\batang.ttc"  # the text of exported books; a .ttf or a .ttc, first face
    tts_port: int = 8766  # the speech pack's server, on this PC only
    narration_timeout: float = 300  # seconds per page; a 26 s page took 50 s


# field -> (environment variable, converter)
_ENV = {
    "host": ("AIAS_HOST", str),
    "port": ("AIAS_PORT", int),
    "data_dir": ("AIAS_DATA_DIR", Path),
    "comfy_url": ("AIAS_COMFY_URL", str),
    "comfy_dir": ("AIAS_COMFY_DIR", Path),
    "comfy_python": ("AIAS_COMFY_PYTHON", str),
    "idle_free_seconds": ("AIAS_IDLE_FREE_SECONDS", float),
    "image_timeout": ("AIAS_IMAGE_TIMEOUT", float),
    "bgm_timeout": ("AIAS_BGM_TIMEOUT", float),
    "ffmpeg": ("AIAS_FFMPEG", str),
    "sprite_gen": ("AIAS_SPRITE_GEN", str),
    "codex_dir": ("AIAS_CODEX_DIR", str),
    "animation_timeout": ("AIAS_ANIMATION_TIMEOUT", float),
    "book_font": ("AIAS_BOOK_FONT", str),
    "tts_port": ("AIAS_TTS_PORT", int),
    "narration_timeout": ("AIAS_NARRATION_TIMEOUT", float),
}


def load_settings() -> Settings:
    overrides = {name: convert(os.environ[var]) for name, (var, convert) in _ENV.items() if os.environ.get(var)}
    return Settings(**overrides)


def is_loopback(host: str) -> bool:
    """Whether `host` is reachable from this PC only (127.x.x.x, ::1 or localhost)."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def find_codex_dir(settings: Settings) -> Path | None:
    """The folder of the codex CLI that animation jobs put first on sprite-gen's PATH.

    The Codex app keeps its own, current CLI at %LOCALAPPDATA%\\OpenAI\\Codex\\bin\\<hash>\\codex.exe. The standalone
    install on PATH (0.147 on this PC) cannot read the app's newer ~/.codex/config.toml and exits at start, so the
    app's CLI goes first. An explicit codex_dir wins, then the newest app CLI; None leaves sprite-gen with the
    `codex` on PATH.
    """
    if settings.codex_dir:
        return Path(settings.codex_dir)
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    found = sorted(Path(local, "OpenAI", "Codex", "bin").glob("*/codex.exe"), key=lambda p: p.stat().st_mtime)
    return found[-1].parent if found else None
