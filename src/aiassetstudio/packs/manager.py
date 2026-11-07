"""Install and remove feature packs under data/packs/<id>/: their own virtual environment, models and Hugging Face home.

An install is a task of its own, not a queue job: a pack belongs to no project, and minutes of download must not hold
up the GPU queue. Progress is `pack_installs.stage`. Nothing is written to the global Hugging Face cache or to ComfyUI.
"""

import asyncio
import logging
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

import httpx

from ..config import Settings, comfy_is_external, engine_comfy_dir, resolve_comfy
from ..store.db import Database, now
from ..store.models import PackInstall
from .catalog import PackFile, PackSpec, load_catalog
from .consent import LicenseChanged, require_consent, verify_licenses
from .download import DownloadError, download, file_sha256

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


def _venv_python(folder: Path) -> Path:
    return folder / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def pack_python(settings: Settings, pack_id: str) -> Path:
    return _venv_python(pack_dir(settings, pack_id))


def _force_remove(function, path, _error) -> None:
    """git keeps its objects read-only, which Windows will not delete."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


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

    def root(self, pack: PackSpec) -> Path:
        """The folder a pack's file paths are relative to."""
        if pack.engine == "comfy_models":
            return resolve_comfy(self.settings) / "models"
        return pack_dir(self.settings, pack.id)

    def adopted(self, pack: PackSpec) -> list[str]:
        """Files of the pack that were already there. They are used, and a removal leaves them."""
        row = self.db.get_install(pack.id)
        if pack.engine != "comfy_models" or row is None or row.status != "installed":
            return []
        return [f.dest for f in pack.files if f.dest not in row.files]

    def is_external(self, pack: PackSpec) -> bool:
        """An engine pack that is not needed, because a ComfyUI this app did not install is in use."""
        return pack.engine == "comfy_engine" and comfy_is_external(self.settings)

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
        if self.is_external(pack):
            raise PackError(f"Studio uses the ComfyUI in {self.settings.comfy_dir}; it needs no engine pack")
        if pack.engine == "comfy_models" and not (resolve_comfy(self.settings) / "main.py").is_file():
            raise PackError(f"pack {pack_id} goes into ComfyUI; install the engine pack first")
        require_consent(self.db, pack)
        directory = pack_dir(self.settings, pack_id)
        directory.mkdir(parents=True, exist_ok=True)
        free, needed = self.disk_free(directory), pack.tested.disk_gb * 2**30
        if free < needed:
            raise InsufficientDisk(
                f"pack {pack_id} needs {pack.tested.disk_gb} GB of free disk; {free / 2**30:.1f} GB is free"
            )
        # Recorded before anything exists, so a failed or cancelled install can be removed too.
        # A model pack's files are recorded one by one instead: only those it really puts down.
        files = {
            "python_sidecar": [
                ".venv",
                "hf",
                "server.py",
                *(p for f in pack.files for p in (f.dest, f"{f.dest}.part")),
            ],
            "comfy_engine": ["ComfyUI"],
            "comfy_models": [],
        }[pack.engine]
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
        pack = self.catalog[pack_id]
        if pack.engine == "comfy_engine" and any(
            other.engine == "comfy_models" and (saved := self.db.get_install(other.id)) and saved.files
            for other in self.catalog.values()
        ):
            raise PackError("the image and video packs are inside this ComfyUI; remove them first")
        root = self.root(pack).resolve()
        for rel in row.files:
            path = (root / rel).resolve()
            if not path.is_relative_to(root):
                raise PackError(f"pack {pack_id} recorded a path outside its folder: {rel}")
            if path.is_dir():
                shutil.rmtree(path, onexc=_force_remove)
            else:
                path.unlink(missing_ok=True)
        directory = pack_dir(self.settings, pack_id).resolve()
        shutil.rmtree(directory / "licenses", ignore_errors=True)
        (directory / LOG_NAME).unlink(missing_ok=True)
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
                await self._file(client, pack, file, i)
        if pack.engine == "comfy_models":
            return
        if pack.git is not None:
            await self._clone(pack, directory)
        await self._environment(pack, directory)
        script = SIDECAR_SCRIPT.get(pack.feature)
        if script:
            shutil.copyfile(ASSETS_DIR / script, directory / "server.py")

    async def _file(self, client: httpx.AsyncClient, pack: PackSpec, file: PackFile, index: int) -> None:
        root = self.root(pack)
        of = f"{index}/{len(pack.files)} {Path(file.dest).name}"
        if pack.engine == "comfy_models":
            dest = root / file.dest
            if dest.is_file():
                self._stage(pack.id, f"checking {of}")
                if await asyncio.to_thread(file_sha256, dest) == file.sha256:
                    return
                raise PackError(f"{dest} is already there but is a different file; Studio will not replace it")
            saved = self.db.get_install(pack.id).files
            self.db.save_install(pack.id, files=[*saved, file.dest, f"{file.dest}.part"])
        self._stage(pack.id, f"downloading {of}")
        shown = 0.0

        def progress(done: int) -> None:
            nonlocal shown
            share = done / file.size
            if share - shown >= PROGRESS_STEP:
                shown = share
                self._stage(pack.id, f"downloading {of} {share:.0%}")

        await download(client, file.url, root / file.dest, file.size, file.sha256, progress)

    async def _run_step(self, pack: PackSpec, cwd: Path, stage: str, args: list[str]) -> None:
        directory = pack_dir(self.settings, pack.id)
        log_path = directory / LOG_NAME
        env = dict(os.environ, HF_HOME=str(directory / "hf"), PYTHONIOENCODING="utf-8")
        self._stage(pack.id, stage)
        code = await self.run(args, cwd, log_path, env)
        if code != 0:
            raise PackError(f"{stage} failed (exit {code}); see {log_path}")

    async def _clone(self, pack: PackSpec, directory: Path) -> None:
        """The engine at its fixed tag. A partial clone from a failed try is replaced."""
        target = directory / "ComfyUI"
        if (target / "main.py").is_file():
            return
        if target.exists():
            shutil.rmtree(target, onexc=_force_remove)
        args = ["git", "clone", "--depth", "1", "--branch", pack.git.tag, pack.git.url, "ComfyUI"]
        await self._run_step(pack, directory, "cloning ComfyUI", args)

    async def _environment(self, pack: PackSpec, directory: Path) -> None:
        """The pack's own Python, or the engine's inside its clone. torch comes last: `qwen-tts` pulls the CPU build,
        which would otherwise stay."""
        home = engine_comfy_dir(self.settings) if pack.git is not None else directory
        python = str(_venv_python(home))

        async def step(stage: str, args: list[str]) -> None:
            await self._run_step(pack, home, stage, args)

        if not Path(python).is_file():
            await step("creating environment", ["uv", "venv", "--python", pack.python, ".venv"])
        packages = ["-r", "requirements.txt"] if pack.git is not None else pack.requirements
        await step("installing packages", ["uv", "pip", "install", "--python", python, *packages])
        names = [p.split("==")[0] for p in pack.torch_packages]
        await step("removing CPU torch", ["uv", "pip", "uninstall", "--python", python, *names])
        await step(
            "installing torch",
            ["uv", "pip", "install", "--python", python, "--index-url", pack.torch_index, *pack.torch_packages],
        )
        await step("checking the GPU", [python, "-c", TORCH_CHECK])
