"""The speech pack's server as a child of the backend.

Unlike ComfyUI it is not shared with other sessions, so it starts for a job and ends when the GPU is wanted elsewhere.
A child, not a detached process: it holds its stdin open and exits when the backend does (assets/tts_server.py).
"""

import asyncio
import logging
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx

from ..config import Settings
from ..store.files import logs_dir
from .catalog import PackSpec
from .manager import pack_dir, pack_python

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
START_TIMEOUT = 300.0  # a first load from a cold disk took 92 s
POLL_INTERVAL = 1.0
STOP_WAIT = 10.0


class SidecarError(RuntimeError):
    """The server could not start or refused a request; the message is meant for the person."""


class SidecarManager:
    def __init__(
        self,
        settings: Settings,
        pack: PackSpec | None,
        port: int | None = None,
        command: Sequence[str] | None = None,
        start_timeout: float = START_TIMEOUT,
        interval: float = POLL_INTERVAL,
    ):
        self.settings = settings
        self.pack = pack
        self.port = port or settings.tts_port
        self.command = command
        self.start_timeout = start_timeout
        self.interval = interval
        self._process: asyncio.subprocess.Process | None = None
        self._http = httpx.AsyncClient(base_url=f"http://{HOST}:{self.port}", timeout=httpx.Timeout(10.0))
        self._lock = asyncio.Lock()

    @property
    def log_path(self) -> Path:
        return logs_dir(self.settings) / "sidecar.log"

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def is_up(self) -> bool:
        """The server of this process answers and its model is loaded."""
        if not self.running:
            return False
        try:
            response = await self._http.get("/health", timeout=3.0)
        except httpx.TransportError:
            return False
        return response.status_code == 200 and response.json().get("ready") is True

    async def ensure(self) -> None:
        """Return once the model is loaded, starting the server if needed. Raises SidecarError on failure."""
        async with self._lock:  # one start even if several callers find it down
            if await self.is_up():
                return
            if not self.running:
                await self._start()
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.start_timeout
            while loop.time() < deadline:
                await asyncio.sleep(self.interval)
                if not self.running:
                    raise SidecarError(f"the speech server stopped while starting; see {self.log_path}")
                if await self.is_up():
                    log.info("speech server is up")
                    return
            await self._stop()
            raise SidecarError(f"the speech server did not start within {self.start_timeout:g} s; see {self.log_path}")

    async def _start(self) -> None:
        args, cwd = self._program()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log.info("starting the speech server on port %d (log: %s)", self.port, self.log_path)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        if self.pack is not None:
            env["HF_HOME"] = str(pack_dir(self.settings, self.pack.id) / "hf")
        # No console window: the backend runs detached, and a console program started from it would open one.
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        with self.log_path.open("ab") as out:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )

    def _program(self) -> tuple[list[str], Path]:
        if self.command is not None:
            return [*self.command, "--port", str(self.port)], Path.cwd()
        if self.pack is None:
            raise SidecarError("no speech pack in the catalog")
        directory = pack_dir(self.settings, self.pack.id)
        python = pack_python(self.settings, self.pack.id)
        if not python.is_file() or not (directory / "server.py").is_file():
            raise SidecarError(f"the {self.pack.id} pack is not installed in {directory}")
        model = directory / self.pack.model_dir
        return [str(python), "server.py", "--port", str(self.port), "--model", str(model)], directory

    async def stop(self) -> None:
        async with self._lock:
            await self._stop()

    async def _stop(self) -> None:
        process, self._process = self._process, None
        if process is None or process.returncode is not None:
            return
        log.info("stopping the speech server")
        process.kill()  # nothing to save, and on Windows there is no gentler way to end it
        try:
            await asyncio.wait_for(process.wait(), STOP_WAIT)
        except TimeoutError:
            log.warning("the speech server did not exit within %g s", STOP_WAIT)

    async def speak(self, body: dict, timeout: float) -> dict:
        """One text to one WAV at body["out_path"]."""
        try:
            response = await self._http.post("/speak", json=body, timeout=timeout)
        except httpx.TransportError as e:
            raise SidecarError(f"the speech server did not answer: {e!r}; see {self.log_path}") from e
        if response.status_code != 200:
            raise SidecarError(f"the speech server answered HTTP {response.status_code}: {response.text[:300]}")
        return response.json()

    async def aclose(self) -> None:
        await self.stop()
        await self._http.aclose()
