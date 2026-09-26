"""Start ComfyUI when it is not running.

ComfyUI keeps running after the backend stops, because other sessions use the same ComfyUI, and it is started
outside any Claude Code session (aiassetstudio.detach) so that closing one does not stop it. It has no console
window; its output goes to data/logs/comfyui.log.
"""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from ..config import Settings
from ..detach import spawn_detached
from ..store.files import logs_dir
from .client import ComfyClient, ComfyUnavailable

log = logging.getLogger(__name__)

LAUNCH_TIMEOUT = 120.0
POLL_INTERVAL = 2.0


class ComfyLauncher:
    def __init__(
        self,
        settings: Settings,
        client: ComfyClient,
        spawn: Callable[..., object] = spawn_detached,
        timeout: float = LAUNCH_TIMEOUT,
        interval: float = POLL_INTERVAL,
    ):
        self.settings = settings
        self.client = client
        self.spawn = spawn
        self.timeout = timeout
        self.interval = interval
        self._lock = asyncio.Lock()

    @property
    def log_path(self) -> Path:
        return logs_dir(self.settings) / "comfyui.log"

    async def ensure(self) -> None:
        """Return once ComfyUI answers, starting it first if needed. Raises ComfyUnavailable on failure."""
        if await self.client.is_up():
            return
        async with self._lock:  # one launch even if several callers find ComfyUI down
            if await self.client.is_up():
                return
            await asyncio.to_thread(self._launch)  # the WMI call takes about a second
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.timeout
            while loop.time() < deadline:
                await asyncio.sleep(self.interval)
                if await self.client.is_up():
                    log.info("ComfyUI is up")
                    return
            raise ComfyUnavailable(f"ComfyUI did not start within {self.timeout:g} s; see {self.log_path}")

    def _launch(self) -> None:
        comfy_dir = self.settings.comfy_dir
        # A venv install by default; the portable build keeps its Python in ..\python_embeded (AIAS_COMFY_PYTHON).
        python = Path(self.settings.comfy_python or comfy_dir / ".venv" / "Scripts" / "python.exe")
        if not python.is_file() or not (comfy_dir / "main.py").is_file():
            raise ComfyUnavailable(
                f"ComfyUI not found: expected {python} and {comfy_dir / 'main.py'} "
                "(set AIAS_COMFY_DIR, and AIAS_COMFY_PYTHON if its Python is not in .venv)"
            )
        port = urlparse(self.settings.comfy_url).port or 8188
        log.info("starting ComfyUI on port %d (log: %s)", port, self.log_path)
        self.spawn([str(python), "main.py", "--port", str(port)], cwd=comfy_dir, log_path=self.log_path)
