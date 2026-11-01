"""`aiassetstudio doctor`: what this PC has against what Studio was tested on. It reads and changes nothing.

Each check is {id, status, detail, fix}; agents read these keys, so they do not change. `fix` is for a person to read,
never a command to run. `warn` means this PC differs from the tested one, not that it cannot work.
"""

import ctypes
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .comfy.preflight import VERIFIED_COMFYUI
from .config import Settings, resolve_comfy
from .packs.catalog import load_catalog

TESTED_VRAM_MIB = 15500  # a card sold as 16 GB reports a little under 16384 MiB
TESTED_RAM_GB = 31  # 32 GB of RAM reports a little under 32
HTTP_TIMEOUT = 2.0
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _check(id: str, status: str, detail: str, fix: str = "") -> dict:
    return {"id": id, "status": status, "detail": detail, "fix": fix}


def nvidia_gpu() -> tuple[str, str, int] | None:
    """(name, driver, memory in MiB) of the first NVIDIA GPU, or None."""
    query = "--query-gpu=name,driver_version,memory.total"
    try:
        done = subprocess.run(
            ["nvidia-smi", query, "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = done.stdout.strip().splitlines()
    if done.returncode != 0 or not lines:
        return None
    name, driver, memory = (part.strip() for part in lines[0].split(","))
    return name, driver, int(memory)


def ram_gb() -> float:
    if sys.platform != "win32":
        import os

        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.ullTotalPhys / 2**30


def free_disk_gb(path: Path) -> float:
    existing = next(p for p in (path, *path.parents) if p.exists())
    return shutil.disk_usage(existing).free / 2**30


def program(name: str) -> str | None:
    return shutil.which(name)


def comfy_version(url: str) -> str | None:
    """ComfyUI's version if it answers at `url`."""
    try:
        response = httpx.get(f"{url}/system_stats", timeout=HTTP_TIMEOUT)
        return response.json().get("system", {}).get("comfyui_version", "?") if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


def backend_up(url: str) -> bool:
    try:
        return httpx.get(f"{url}/api/health", timeout=HTTP_TIMEOUT).status_code == 200
    except httpx.HTTPError:
        return False


def port_taken(host: str, port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1.0)
        return probe.connect_ex((host, port)) == 0


def _os() -> dict:
    name = f"{platform.system()} {platform.release()}"
    if sys.platform == "win32":
        return _check("os", "ok", name)
    return _check("os", "warn", name, "Studio was tested on Windows 11 only.")


def _gpu() -> list[dict]:
    gpu = nvidia_gpu()
    if gpu is None:
        fix = "Install an NVIDIA GPU driver; image, music and speech jobs need an NVIDIA GPU."
        return [_check("gpu", "fail", "no NVIDIA GPU answered nvidia-smi", fix), _check("vram", "warn", "unknown")]
    name, driver, memory = gpu
    vram = _check("vram", "ok", f"{memory} MiB")
    if memory < TESTED_VRAM_MIB:
        vram = _check("vram", "warn", f"{memory} MiB, tested on 16 GB", "Jobs may run out of GPU memory.")
    return [_check("gpu", "ok", f"{name}, driver {driver}"), vram]


def _ram() -> dict:
    total = ram_gb()
    if total < TESTED_RAM_GB:
        return _check("ram", "warn", f"{total:.1f} GB, tested on 32 GB", "Large models may run out of memory.")
    return _check("ram", "ok", f"{total:.1f} GB")


def _disk(settings: Settings) -> dict:
    free = free_disk_gb(settings.data_dir)
    needed = max((pack.tested.disk_gb for pack in load_catalog().values()), default=0)
    if free < needed:
        return _check("disk", "warn", f"{free:.1f} GB free", f"Feature packs need {needed} GB. Free some disk space.")
    return _check("disk", "ok", f"{free:.1f} GB free")


def _program_check(name: str, needed_for: str, get_it: str) -> dict:
    path = program(name)
    if path is None:
        return _check(name, "fail", f"not on PATH; needed for {needed_for}", get_it)
    return _check(name, "ok", path)


def _comfyui(settings: Settings) -> dict:
    version = comfy_version(settings.comfy_url)
    if version is None:
        comfy_dir = resolve_comfy(settings)
        if (comfy_dir / "main.py").is_file():
            return _check("comfyui", "ok", f"installed in {comfy_dir}, not running; jobs start it")
        fix = "Install the engine-comfyui pack in the gallery, or set AIAS_COMFY_DIR to a ComfyUI you have."
        return _check("comfyui", "warn", f"not found in {settings.comfy_dir}", fix)
    if version != VERIFIED_COMFYUI:
        detail = f"running version {version}; the graphs were verified on {VERIFIED_COMFYUI}"
        return _check("comfyui", "warn", detail, "Node names can change between versions; run `aiassetstudio check`.")
    return _check("comfyui", "ok", f"running version {version} at {settings.comfy_url}")


def _ports(settings: Settings, backend: bool, comfy_up: bool) -> list[dict]:
    comfy_port = urlparse(settings.comfy_url).port or 8188
    owners = {
        settings.port: ("Studio", backend),
        comfy_port: ("ComfyUI", comfy_up),
        settings.tts_port: ("speech", False),
    }
    checks = []
    for port, (owner, up) in owners.items():
        id = f"port_{port}"
        if not port_taken("127.0.0.1", port):
            checks.append(_check(id, "ok", "free"))
        elif up:
            checks.append(_check(id, "ok", f"used by {owner}"))
        else:
            checks.append(
                _check(id, "warn", f"in use by another program; {owner} needs it", "Close it or change the port.")
            )
    return checks


def run_checks(settings: Settings) -> list[dict]:
    backend = backend_up(f"http://{settings.host}:{settings.port}")
    comfy = _comfyui(settings)
    font = Path(settings.book_font)
    return [
        _os(),
        *_gpu(),
        _ram(),
        _disk(settings),
        _program_check("uv", "feature packs", "Install uv: https://docs.astral.sh/uv/"),
        _program_check("ffmpeg", "OGG and MP3 files", "Install ffmpeg and put it on PATH, or set AIAS_FFMPEG."),
        comfy,
        _check("backend", "ok", "running" if backend else "not running; `aiassetstudio setup` starts it"),
        *_ports(settings, backend, comfy["detail"].startswith("running")),
        _check("font", "ok", str(font))
        if font.is_file()
        else _check("font", "warn", f"{font} not found", "PDF export needs a Korean font; set AIAS_BOOK_FONT."),
    ]


def failed(checks: list[dict]) -> list[dict]:
    return [check for check in checks if check["status"] == "fail"]
