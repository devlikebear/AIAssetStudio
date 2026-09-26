"""Start long-running helpers (the backend, ComfyUI) so that they outlive whoever starts them.

A Claude Code session runs its processes in a Windows job, and they all die when the session ends: a child stays in
the job even with DETACHED_PROCESS, and the job refuses CREATE_BREAKAWAY_FROM_JOB (checked 2026-09-25: backends that
an MCP server or a tool call had started died with their session, while a process created through WMI lived on for
hours). So on Windows the process is created by WMI (Win32_Process.Create), outside the caller's jobs, in the same
Windows session. WMI gives it the user's default environment and no output redirection, so what it runs is a short
launcher step, `python -m aiassetstudio.detach <spec>`, which applies the working directory, the environment the
caller set for this app and the log file, starts the real process and exits. The job WMI puts processes in has no
limits and lets their children leave it. Elsewhere a new session is enough.
"""

import base64
import json
import logging
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

log = logging.getLogger(__name__)

# Windows-only flags; getattr keeps the module importable elsewhere.
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WMI_TIMEOUT = 60.0

# The launcher runs without a console (CreateFlags 8 = DETACHED_PROCESS) and hidden.
_WMI_CREATE = """
$startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly `
    -Property @{ShowWindow = [uint16]0; CreateFlags = [uint32]8}
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $env:AIAS_DETACH_COMMAND; CurrentDirectory = $env:AIAS_DETACH_CWD
    ProcessStartupInformation = $startup}
"$($r.ReturnValue) $($r.ProcessId)"
"""


class SpawnError(RuntimeError):
    """WMI could not create the process."""


def passed_env() -> dict[str, str]:
    """What the started process must see beyond the user's default environment: this app's settings (AIAS_*, e.g. a
    test port and data folder) and the caller's PATH (ffmpeg)."""
    env = {k: v for k, v in os.environ.items() if k.startswith("AIAS_") or k.upper() == "PATH"}
    # Output goes to a log file, not a console: without this Python writes cp949 on Korean Windows and fails on
    # characters outside it.
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def encode_spec(args: Sequence[str], cwd: Path, log_path: Path, env: dict[str, str]) -> str:
    spec = {"args": [str(a) for a in args], "cwd": str(cwd), "log": str(log_path), "env": env}
    return base64.urlsafe_b64encode(json.dumps(spec).encode()).decode()  # no quoting issues on a command line


def decode_spec(text: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(text.encode()))


def spawn_detached(args: Sequence[str], cwd: Path, log_path: Path) -> None:
    """Start `args` in `cwd`, output appended to `log_path`, so that it keeps running after this process, and its
    Claude Code session if any, have ended. Returns once the process is created, not when it is ready."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = passed_env()
    if sys.platform == "win32":
        spec = encode_spec(args, Path(cwd), log_path, env)
        command = subprocess.list2cmdline([sys.executable, "-m", "aiassetstudio.detach", spec])
        try:
            pid = wmi_create(command, Path(cwd))
            log.info("started %s through WMI (launcher pid %d)", Path(args[0]).name, pid)
            return
        except (OSError, SpawnError, subprocess.SubprocessError) as e:
            log.warning(
                "could not start %s through WMI (%s); starting it directly, so it stops with this session",
                Path(args[0]).name,
                e,
            )
    start(args, Path(cwd), log_path, env)


def start(args: Sequence[str], cwd: Path, log_path: Path, env: dict[str, str]) -> None:
    """The process itself: no console, stdin closed, output appended to the log."""
    flags = {"creationflags": DETACHED} if sys.platform == "win32" else {"start_new_session": True}
    with open(log_path, "ab") as out:
        subprocess.Popen(
            [str(a) for a in args],
            cwd=cwd,
            env=os.environ | env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            close_fds=True,
            **flags,
        )


def wmi_create(command: str, cwd: Path) -> int:
    """Win32_Process.Create through PowerShell; returns the new process id. The command and folder travel in
    environment variables, so nothing is interpolated into the script."""
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _WMI_CREATE],
        env=os.environ | {"AIAS_DETACH_COMMAND": command, "AIAS_DETACH_CWD": str(cwd)},
        capture_output=True,
        text=True,
        timeout=WMI_TIMEOUT,
        creationflags=NO_WINDOW,  # the backend has no console: a console program would open a window
        check=False,
    )
    parts = done.stdout.split()
    if done.returncode != 0 or len(parts) != 2 or parts[0] != "0":
        # ReturnValue: 2 access denied, 3 insufficient privilege, 9 path not found, 21 invalid parameter
        raise SpawnError(f"Win32_Process.Create failed: {done.stdout.strip()} {done.stderr.strip()[-500:]}")
    return int(parts[1])


def main(argv: Sequence[str] | None = None) -> None:
    """The launcher step that WMI runs: start the real process described by the spec, then exit."""
    spec = decode_spec((argv if argv is not None else sys.argv)[1])
    try:
        start(spec["args"], Path(spec["cwd"]), Path(spec["log"]), spec["env"])
    except Exception as e:  # nobody sees this process's output: leave the reason in the log
        with open(spec["log"], "a", encoding="utf-8") as out:
            out.write(f"aiassetstudio.detach: could not start {spec['args']}: {e!r}\n")
        raise


if __name__ == "__main__":
    main()
