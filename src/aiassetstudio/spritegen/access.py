"""Whether animations can run: sprite-gen installed, and the codex CLI it calls logged in to ChatGPT."""

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import Settings, find_codex_dir

LOGIN_TIMEOUT = 20.0  # seconds; `codex login status` answers in well under a second
CODEX_EXE = "codex.exe" if sys.platform == "win32" else "codex"


def codex_command(settings: Settings) -> list[str] | None:
    """How to run the codex CLI that sprite-gen will find: the one in find_codex_dir, else the codex on PATH."""
    folder = find_codex_dir(settings)
    if folder is None:
        found = shutil.which("codex")
        return [found] if found else None
    for name in (CODEX_EXE, "codex.py"):  # codex.py: the tests' stand-in, run with this Python
        if (folder / name).is_file():
            return [sys.executable, str(folder / name)] if name.endswith(".py") else [str(folder / name)]
    return None


async def codex_login(command: list[str]) -> str:
    """ "ready" when `codex login status` says it is logged in, else what it said instead."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            "login",
            "status",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            creationflags=flags,
        )
    except OSError as e:
        return f"cannot run codex: {e}"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), LOGIN_TIMEOUT)
    except TimeoutError:
        proc.kill()
        return f"codex login status gave no answer within {LOGIN_TIMEOUT:g} s"
    text = (out + err).decode("utf-8", "replace").strip()
    if proc.returncode == 0 and "Logged in" in text:  # "Logged in using ChatGPT" (on stderr)
        return "ready"
    return (text.splitlines() or [f"exit {proc.returncode}"])[-1][:200]


async def animation_status(settings: Settings) -> dict:
    """{ok, reason, sprite_gen, codex, login}; `reason` says what to fix when not ok."""
    sprite_gen = Path(settings.sprite_gen)
    command = codex_command(settings)
    login = await codex_login(command) if command else "missing"
    problems = []
    if not sprite_gen.is_file():
        problems.append(f"sprite-gen not found at {sprite_gen} (install it, or set AIAS_SPRITE_GEN)")
    if command is None:
        problems.append("codex CLI not found (install the Codex app, or set AIAS_CODEX_DIR)")
    elif login != "ready":
        problems.append(f"codex is not logged in ({login}); run `codex login` and sign in with ChatGPT")
    return {
        "ok": not problems,
        "reason": "; ".join(problems) or None,
        "sprite_gen": str(sprite_gen) if sprite_gen.is_file() else None,
        "codex": command[-1] if command else None,
        "login": login,
    }
