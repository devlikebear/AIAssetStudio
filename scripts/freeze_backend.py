"""Freeze the backend into desktop/src-tauri/backend/ for the Tauri bundle (local builds and release CI).

Standard library only; needs `uv` on PATH and a built web/dist. The one-folder layout, the flags and the
web/dist-next-to-exe trick come from docs/plans/notes/studio-pyinstaller-freeze.md. The temp venv resolves
fresh (not from uv.lock), which matched the lock when measured; a drift would show up in selftest or tests.
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUILD = REPO / "desktop" / "src-tauri" / "backend-build"
OUT = REPO / "desktop" / "src-tauri" / "backend"


def run(cmd: list) -> None:
    print(">", *map(str, cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def main() -> int | str:
    if not sys.platform.startswith("win"):
        return "the desktop shell ships for Windows only; freeze there"
    gallery = REPO / "web" / "dist"
    if not (gallery / "index.html").is_file():
        return "web/dist is missing; run `npm run build` in web/ first"

    venv_python = BUILD / "venv" / "Scripts" / "python.exe"
    if not venv_python.is_file():
        run(["uv", "venv", BUILD / "venv", "--python", "3.13"])
    run(["uv", "pip", "install", "--python", venv_python, REPO, "pyinstaller"])
    run(
        [
            venv_python,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--onedir",
            "--name",
            "aiassetstudio-backend",
            # librosa picks submodules through lazy_loader and uvicorn through importlib strings,
            # which PyInstaller's analysis cannot see.
            "--collect-all",
            "librosa",
            "--collect-submodules",
            "uvicorn",
            "--distpath",
            BUILD / "dist",
            "--workpath",
            BUILD / "work",
            "--specpath",
            BUILD,
            REPO / "scripts" / "backend_launcher.py",
        ]
    )
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(BUILD / "dist" / "aiassetstudio-backend", OUT)
    # Frozen REPO_ROOT is the exe folder, so the backend serves <exe dir>/web/dist as the gallery.
    shutil.copytree(gallery, OUT / "web" / "dist")
    run([OUT / "aiassetstudio-backend.exe", "selftest"])
    print(f"frozen backend ready: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
