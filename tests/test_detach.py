import ctypes
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path

import pytest

from aiassetstudio import detach
from aiassetstudio.detach import decode_spec, encode_spec, passed_env, spawn_detached

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows jobs and WMI")


def test_spec_round_trip(tmp_path):
    env = {"AIAS_PORT": "8766", "PATH": r"C:\tools;C:\ffmpeg"}
    spec = encode_spec(["python", "-c", 'print("a b")'], tmp_path, tmp_path / "x.log", env)
    assert spec.isascii() and " " not in spec and '"' not in spec  # safe as one command-line argument
    assert decode_spec(spec) == {
        "args": ["python", "-c", 'print("a b")'],
        "cwd": str(tmp_path),
        "log": str(tmp_path / "x.log"),
        "env": env,
    }


def test_passed_env(monkeypatch):
    monkeypatch.setenv("AIAS_DATA_DIR", r"C:\tmp\data")
    monkeypatch.setenv("SECRET_TOKEN", "do-not-pass")
    env = passed_env()
    assert env["AIAS_DATA_DIR"] == r"C:\tmp\data"
    assert "SECRET_TOKEN" not in env  # only this app's settings and PATH travel to the new process
    assert env["PYTHONIOENCODING"] == "utf-8"


@windows_only
def test_spawn_goes_through_wmi(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(detach, "wmi_create", lambda command, cwd: calls.append((command, cwd)) or 1234)
    spawn_detached(["python", "-m", "aiassetstudio", "serve"], tmp_path, tmp_path / "logs" / "backend.log")
    [(command, cwd)] = calls
    assert cwd == tmp_path
    launcher, spec = subprocess.list2cmdline([sys.executable, "-m", "aiassetstudio.detach"]), command.rsplit(" ", 1)[1]
    assert command.startswith(launcher)
    assert decode_spec(spec)["args"] == ["python", "-m", "aiassetstudio", "serve"]
    assert (tmp_path / "logs").is_dir()


@windows_only
def test_falls_back_to_a_direct_start(monkeypatch, tmp_path):
    def broken(command, cwd):
        raise detach.SpawnError("WMI is not available")

    started = []
    monkeypatch.setattr(detach, "wmi_create", broken)
    monkeypatch.setattr(detach, "start", lambda *args: started.append(args))
    spawn_detached(["python", "x.py"], tmp_path, tmp_path / "x.log")
    assert started and started[0][0] == ["python", "x.py"]


def test_launcher_step_writes_the_log(tmp_path):
    # What WMI runs: `python -m aiassetstudio.detach <spec>` starts the real process with the spec's env and log.
    script = "import os; print('hello', os.environ['AIAS_TEST_VALUE'], flush=True)"
    spec = encode_spec([sys.executable, "-c", script], tmp_path, tmp_path / "out.log", {"AIAS_TEST_VALUE": "42"})
    subprocess.run([sys.executable, "-m", "aiassetstudio.detach", spec], check=True, timeout=30)
    deadline = time.monotonic() + 20
    while "hello 42" not in (tmp_path / "out.log").read_text(errors="replace") and time.monotonic() < deadline:
        time.sleep(0.1)
    assert "hello 42" in (tmp_path / "out.log").read_text()


# --- a Claude Code session in miniature: a job whose processes are all terminated --------------------------------

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
STILL_ACTIVE = 259
SLEEPER = "import os, pathlib, sys, time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(120)"


def alive(k32, pid: int) -> bool:
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(handle, ctypes.byref(code))
    k32.CloseHandle(handle)
    return code.value == STILL_ACTIVE


def wait_for(path: Path, parent: subprocess.Popen, timeout: float = 30) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.read_text():
            return int(path.read_text())
        assert parent.poll() is None, f"the parent exited with {parent.returncode} before {path.name} appeared"
        time.sleep(0.1)
    raise TimeoutError(f"{path} did not appear")


@windows_only
def test_spawned_process_outlives_its_job(tmp_path):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    name = f"Local\\aiassetstudio-test-{uuid.uuid4().hex}"
    job = k32.CreateJobObjectW(None, name)
    assert job, ctypes.get_last_error()
    survivor_pid_file, control_pid_file = tmp_path / "survivor.pid", tmp_path / "control.pid"
    # The parent joins the job, then starts one sleeper with spawn_detached and one the old way (Popen, detached).
    parent_code = f"""
import ctypes, subprocess, sys, time
from ctypes import wintypes
k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenJobObjectW.restype = wintypes.HANDLE
k.GetCurrentProcess.restype = wintypes.HANDLE
k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
job = k.OpenJobObjectW(0x1F001F, False, {name!r})
assert job and k.AssignProcessToJobObject(job, k.GetCurrentProcess()), ctypes.get_last_error()
from aiassetstudio.detach import DETACHED, spawn_detached
spawn_detached([sys.executable, "-c", {SLEEPER!r}, {str(survivor_pid_file)!r}], {str(tmp_path)!r},
               {str(tmp_path / "survivor.log")!r})
subprocess.Popen([sys.executable, "-c", {SLEEPER!r}, {str(control_pid_file)!r}], creationflags=DETACHED)
time.sleep(120)
"""
    parent = subprocess.Popen([sys.executable, "-c", parent_code])
    try:
        survivor, control = wait_for(survivor_pid_file, parent), wait_for(control_pid_file, parent)
        assert alive(k32, survivor) and alive(k32, control)
        assert k32.TerminateJobObject(job, 1), ctypes.get_last_error()  # what ending a session does
        parent.wait(timeout=10)
        deadline = time.monotonic() + 5
        while alive(k32, control) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not alive(k32, control), "a plain detached child should die with its job (the old behaviour)"
        assert alive(k32, survivor), "spawn_detached must start the process outside the job"
    finally:
        for pid_file in (survivor_pid_file, control_pid_file):
            if pid_file.is_file() and pid_file.read_text():
                handle = k32.OpenProcess(PROCESS_TERMINATE, False, int(pid_file.read_text()))
                if handle:
                    k32.TerminateProcess(handle, 0)
                    k32.CloseHandle(handle)
        parent.kill()
        k32.CloseHandle(job)
