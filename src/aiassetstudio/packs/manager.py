"""Install and remove feature packs under data/packs/<id>/: their own virtual environment, models and Hugging Face home.

An install is a task of its own, not a queue job: a pack belongs to no project, and minutes of download must not hold
up the GPU queue. Progress is `pack_installs.stage`. Nothing is written to the global Hugging Face cache or to ComfyUI.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

import httpx

from ..config import Settings
from ..store.db import Database, now
from ..store.models import PackInstall
from .catalog import PackSpec, load_catalog
from .consent import LicenseChanged, require_consent, verify_licenses
from .download import DownloadError, download

log = logging.getLogger(__name__)

CommandRunner = Callable[[Sequence[str], Path, Path, dict[str, str]], Awaitable[int]]
ASSETS_DIR = Path(__file__).with_name("assets")
LOG_NAME = "install.log"
LOG_TAIL = 2000  # characters of the install log shown in the gallery
PROGRESS_STEP = 0.01  # share of a file between two writes of the stage
TORCH_CHECK = "import sys, torch; sys.exit(0 if torch.cuda.is_available() else 1)"
SIDECAR_SCRIPT = {"audiobook": "tts_server.py"}
KILL_WAIT = 10.0


class PackError(RuntimeError):
    """An install could not start or failed; the message is meant for the person."""


class InsufficientDisk(PackError):
    pass


async def run_command(args: Sequence[str], cwd: Path, log_path: Path, env: dict[str, str]) -> int:
    """Run a program with its output appended to the install log; killed if the install is cancelled."""
    # No console window: the backend runs detached, and a console program started from it would open one.
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with log_path.open("ab") as out:
        out.write(f"\n> {' '.join(args)}\n".encode())
        out.flush()
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        try:
            return await process.wait()
        except asyncio.CancelledError:
            process.kill()
            await asyncio.wait_for(asyncio.shield(process.wait()), KILL_WAIT)
            raise


def packs_dir(settings: Settings) -> Path:
    return settings.data_dir / "packs"


def pack_dir(settings: Settings, pack_id: str) -> Path:
    return packs_dir(settings) / pack_id


def pack_python(settings: Settings, pack_id: str) -> Path:
    bin_dir = ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    return pack_dir(settings, pack_id) / ".venv" / Path(*bin_dir)


class PackManager:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        catalog: dict[str, PackSpec] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        run: CommandRunner = run_command,
        disk_free: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free,
    ):
        self.settings = settings
        self.db = db
        self.catalog = load_catalog() if catalog is None else catalog
        self.transport = transport
        self.run = run
        self.disk_free = disk_free
        self._tasks: dict[str, asyncio.Task] = {}

    def start(self) -> None:
        if stale := self.db.mark_stale_installs_failed():
            log.warning("marked %d pack install(s) left running by a previous process as failed", stale)

    async def stop(self) -> None:
        for pack_id in list(self._tasks):
            await self.cancel(pack_id)

    def pack(self, pack_id: str) -> PackSpec | None:
        return self.catalog.get(pack_id)

    def is_installed(self, pack_id: str) -> bool:
        """The catalog's version of the pack is in place; an older version must be installed again, with consent."""
        pack, row = self.catalog.get(pack_id), self.db.get_install(pack_id)
        return pack is not None and row is not None and row.status == "installed" and row.version == pack.version

    def log_tail(self, pack_id: str) -> str:
        path = pack_dir(self.settings, pack_id) / LOG_NAME
        if not path.is_file():
            return ""
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - LOG_TAIL))
            return f.read().decode("utf-8", "replace")

    def install(self, pack_id: str) -> PackInstall:
        """Start installing in the background. Raises ConsentRequired, InsufficientDisk or PackError at once."""
        pack = self.catalog[pack_id]
        if pack_id in self._tasks:
            raise PackError(f"pack {pack_id} is already being installed")
        if self.is_installed(pack_id):
            raise PackError(f"pack {pack_id} is already installed")
        require_consent(self.db, pack)
        directory = pack_dir(self.settings, pack_id)
        directory.mkdir(parents=True, exist_ok=True)
        free, needed = self.disk_free(directory), pack.tested.disk_gb * 2**30
        if free < needed:
            raise InsufficientDisk(
                f"pack {pack_id} needs {pack.tested.disk_gb} GB of free disk; {free / 2**30:.1f} GB is free"
            )
        # Recorded before anything exists, so a failed or cancelled install can be removed too.
        files = [".venv", "hf", "licenses", "server.py", LOG_NAME]
        files += [f.dest for f in pack.files] + [f"{f.dest}.part" for f in pack.files]
        row = self.db.save_install(
            pack_id, version=pack.version, status="installing", stage="starting", error=None, files=files
        )
        task = asyncio.create_task(self._install(pack), name=f"pack-{pack_id}")
        self._tasks[pack_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(pack_id, None))
        return row

    async def cancel(self, pack_id: str) -> None:
        task = self._tasks.get(pack_id)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def remove(self, pack_id: str) -> None:
        """Delete what the install recorded and nothing else; the folder goes once it is empty."""
        if pack_id in self._tasks:
            raise PackError(f"pack {pack_id} is being installed; cancel it first")
        row = self.db.get_install(pack_id)
        if row is None:
            return
        directory = pack_dir(self.settings, pack_id).resolve()
        for rel in row.files:
            path = (directory / rel).resolve()
            if not path.is_relative_to(directory):
                raise PackError(f"pack {pack_id} recorded a path outside its folder: {rel}")
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        for folder in sorted((p for p in directory.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
            if not any(folder.iterdir()):
                folder.rmdir()
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
        self.db.delete_install(pack_id)

    def _stage(self, pack_id: str, stage: str) -> None:
        self.db.save_install(pack_id, stage=stage)

    async def _install(self, pack: PackSpec) -> None:
        try:
            await self._steps(pack)
        except asyncio.CancelledError:
            self.db.save_install(pack.id, status="cancelled", stage=None, error=None)
            raise
        except LicenseChanged as e:
            self.db.save_install(pack.id, status="failed", stage=None, error=f"license_changed: {e}")
        except (PackError, DownloadError, OSError) as e:
            self.db.save_install(pack.id, status="failed", stage=None, error=str(e))
        except Exception as e:
            log.exception("install of pack %s crashed", pack.id)
            self.db.save_install(pack.id, status="failed", stage=None, error=str(e) or type(e).__name__)
        else:
            self.db.save_install(pack.id, status="installed", stage=None, error=None, installed_at=now())

    async def _steps(self, pack: PackSpec) -> None:
        directory = pack_dir(self.settings, pack.id)
        async with httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(60.0)) as client:
            self._stage(pack.id, "checking licenses")

            async def fetch(url: str) -> bytes:
                try:
                    response = await client.get(url, follow_redirects=True)
                except httpx.TransportError as e:
                    raise PackError(f"could not read the license at {url}: {e!r}") from e
                if response.status_code != 200:
                    raise PackError(f"could not read the license at {url}: HTTP {response.status_code}")
                return response.content

            texts = await verify_licenses(pack, fetch)
            (directory / "licenses").mkdir(exist_ok=True)
            for license_id, text in texts.items():
                (directory / "licenses" / f"{license_id}.txt").write_bytes(text)
            for i, file in enumerate(pack.files, start=1):
                await self._download(client, pack, file, i)
        await self._environment(pack, directory)
        script = SIDECAR_SCRIPT.get(pack.feature)
        if script:
            shutil.copyfile(ASSETS_DIR / script, directory / "server.py")

    async def _download(self, client: httpx.AsyncClient, pack: PackSpec, file, index: int) -> None:
        directory = pack_dir(self.settings, pack.id)
        of = f"{index}/{len(pack.files)} {Path(file.dest).name}"
        self._stage(pack.id, f"downloading {of}")
        shown = 0.0

        def progress(done: int) -> None:
            nonlocal shown
            share = done / file.size
            if share - shown >= PROGRESS_STEP:
                shown = share
                self._stage(pack.id, f"downloading {of} {share:.0%}")

        await download(client, file.url, directory / file.dest, file.size, file.sha256, progress)

    async def _environment(self, pack: PackSpec, directory: Path) -> None:
        """The pack's own Python. torch comes last: `qwen-tts` pulls the CPU build, which would otherwise stay."""
        log_path = directory / LOG_NAME
        env = dict(os.environ, HF_HOME=str(directory / "hf"), PYTHONIOENCODING="utf-8")
        python = str(pack_python(self.settings, pack.id))

        async def step(stage: str, args: list[str]) -> None:
            self._stage(pack.id, stage)
            code = await self.run(args, directory, log_path, env)
            if code != 0:
                raise PackError(f"{stage} failed (exit {code}); see {log_path}")

        if not Path(python).is_file():
            await step("creating environment", ["uv", "venv", "--python", pack.python, ".venv"])
        await step("installing packages", ["uv", "pip", "install", "--python", python, *pack.requirements])
        names = [p.split("==")[0] for p in pack.torch_packages]
        await step("removing CPU torch", ["uv", "pip", "uninstall", "--python", python, *names])
        await step(
            "installing torch",
            ["uv", "pip", "install", "--python", python, "--index-url", pack.torch_index, *pack.torch_packages],
        )
        await step("checking the GPU", [python, "-c", TORCH_CHECK])
