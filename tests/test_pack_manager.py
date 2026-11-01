import asyncio
import hashlib
from pathlib import Path

import httpx
import pytest

from aiassetstudio.config import Settings
from aiassetstudio.packs.catalog import Measured, PackFile, PackLicense, PackSpec
from aiassetstudio.packs.consent import ConsentRequired, accept
from aiassetstudio.packs.download import ChecksumError, DownloadError, download
from aiassetstudio.packs.manager import InsufficientDisk, PackError, PackManager, pack_dir, pack_python
from aiassetstudio.store.db import Database

MODEL = b"model bytes " * 1000
LICENSE = b"license text"
LICENSE_URL = "https://www.apache.org/licenses/LICENSE-2.0.txt"
REVISION = "a" * 40


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_pack(model: bytes = MODEL, license_text: bytes = LICENSE) -> PackSpec:
    return PackSpec(
        id="speech-ko",
        title="test",
        feature="audiobook",
        version="1.0.0",
        engine="python_sidecar",
        model_dir="models/m",
        licenses=[
            PackLicense(
                id="apache-2.0", name="Apache", class_="open", url=LICENSE_URL, sha256=sha(license_text), summary_ko="x"
            )
        ],
        files=[
            PackFile(
                repo="a/b",
                revision=REVISION,
                path="model.bin",
                dest="models/m/model.bin",
                size=len(model),
                sha256=sha(model),
            )
        ],
        requirements=["qwen-tts==0.1.1"],
        python="3.12",
        torch_index="https://download.pytorch.org/whl/cu130",
        torch_packages=["torch==1+cu130", "torchaudio==1+cu130"],
        tested=Measured(vram_gb=16, ram_gb=32, disk_gb=1, os="Windows 11"),
    )


class Hub:
    """Hugging Face and the license host: honours Range, and can stop part way or lie about a file."""

    def __init__(self, model: bytes = MODEL, stop_after: int | None = None, ignore_range: bool = False):
        self.model = model
        self.stop_after = stop_after
        self.ignore_range = ignore_range
        self.ranges: list[str | None] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.apache.org":
            return httpx.Response(200, content=LICENSE)
        header = request.headers.get("range")
        self.ranges.append(header)
        start = int(header.removeprefix("bytes=").removesuffix("-")) if header and not self.ignore_range else 0
        body = self.model[start:]
        if self.stop_after is not None:
            limit, self.stop_after = self.stop_after, None
            return httpx.Response(200 if not start else 206, stream=_Broken(body[:limit]))
        return httpx.Response(206 if start else 200, stream=httpx.ByteStream(body))


class _Broken(httpx.AsyncByteStream):
    def __init__(self, data: bytes):
        self.data = data

    async def __aiter__(self):
        yield self.data
        raise httpx.ReadError("connection lost")


class Commands:
    """Stands in for uv and the pack's Python."""

    def __init__(self, fail_on: str | None = None, hang_on: str | None = None):
        self.calls: list[list[str]] = []
        self.fail_on = fail_on
        self.hang_on = hang_on

    async def __call__(self, args, cwd: Path, log_path: Path, env: dict) -> int:
        self.calls.append(list(args))
        text = " ".join(args)
        if self.hang_on and self.hang_on in text:
            await asyncio.sleep(60)
        return 1 if self.fail_on and self.fail_on in text else 0


@pytest.fixture
def env(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    db = Database(tmp_path / "studio.db")
    made = []

    def make(pack=None, hub=None, commands=None, disk_free=10 * 2**30, consent=True) -> PackManager:
        pack = pack or make_pack()
        manager = PackManager(
            settings,
            db,
            catalog={pack.id: pack},
            transport=httpx.MockTransport(hub or Hub()),
            run=commands or Commands(),
            disk_free=lambda path: disk_free,
        )
        if consent:
            accept(db, pack, ["apache-2.0"])
        made.append(manager)
        return manager

    yield make
    db.close()


async def finished(manager: PackManager, pack_id: str = "speech-ko"):
    if task := manager._tasks.get(pack_id):
        await asyncio.wait_for(asyncio.shield(task), 5)
    return manager.db.get_install(pack_id)


async def test_install_downloads_verifies_and_builds_the_environment(env):
    commands = Commands()
    manager = env(commands=commands)
    manager.install("speech-ko")
    row = await finished(manager)
    assert row.status == "installed", row.error
    assert row.installed_at
    assert manager.is_installed("speech-ko")
    directory = pack_dir(manager.settings, "speech-ko")
    assert (directory / "models/m/model.bin").read_bytes() == MODEL
    assert not (directory / "models/m/model.bin.part").exists()
    assert (directory / "licenses/apache-2.0.txt").read_bytes() == LICENSE
    assert (directory / "server.py").is_file()


async def test_torch_is_replaced_last_and_checked(env):
    commands = Commands()
    manager = env(commands=commands)
    manager.install("speech-ko")
    await finished(manager)
    programs = [c[:3] for c in commands.calls]
    assert programs[:4] == [
        ["uv", "venv", "--python"],
        ["uv", "pip", "install"],
        ["uv", "pip", "uninstall"],
        ["uv", "pip", "install"],
    ]
    assert commands.calls[2][-2:] == ["torch", "torchaudio"]
    assert "--index-url" in commands.calls[3]
    assert commands.calls[-1][0] == str(pack_python(manager.settings, "speech-ko"))
    assert "cuda.is_available" in commands.calls[-1][-1]


async def test_no_gpu_in_torch_fails_the_install(env):
    manager = env(commands=Commands(fail_on="is_available"))
    manager.install("speech-ko")
    row = await finished(manager)
    assert row.status == "failed"
    assert "checking the GPU" in row.error
    assert not manager.is_installed("speech-ko")


async def test_install_without_consent_is_refused(env):
    manager = env(consent=False)
    with pytest.raises(ConsentRequired):
        manager.install("speech-ko")
    assert manager.db.get_install("speech-ko") is None


async def test_too_little_disk_is_refused_before_anything_is_written(env):
    manager = env(disk_free=2**20)
    with pytest.raises(InsufficientDisk):
        manager.install("speech-ko")
    assert manager.db.get_install("speech-ko") is None


async def test_a_changed_license_stops_before_the_download(env):
    hub = Hub()
    manager = env(pack=make_pack(license_text=b"the old text"), hub=hub)
    manager.install("speech-ko")
    row = await finished(manager)
    assert row.status == "failed"
    assert row.error.startswith("license_changed:")
    assert hub.ranges == []


async def test_an_interrupted_download_resumes(env):
    hub = Hub(stop_after=5000)
    manager = env(hub=hub)
    manager.install("speech-ko")
    row = await finished(manager)
    assert row.status == "failed"
    part = pack_dir(manager.settings, "speech-ko") / "models/m/model.bin.part"
    assert part.stat().st_size == 5000

    manager.install("speech-ko")
    row = await finished(manager)
    assert row.status == "installed", row.error
    assert hub.ranges == [None, "bytes=5000-"]
    assert (pack_dir(manager.settings, "speech-ko") / "models/m/model.bin").read_bytes() == MODEL


async def test_a_bad_checksum_fails_and_drops_the_partial_file(env):
    manager = env(hub=Hub(model=b"x" * len(MODEL)))
    manager.install("speech-ko")
    row = await finished(manager)
    assert row.status == "failed"
    assert "sha256" in row.error
    directory = pack_dir(manager.settings, "speech-ko")
    assert not (directory / "models/m/model.bin").exists()
    assert not (directory / "models/m/model.bin.part").exists()


async def test_cancel_stops_the_install(env):
    manager = env(commands=Commands(hang_on="uv venv"))
    manager.install("speech-ko")
    async with asyncio.timeout(3):
        while not any("venv" in c for c in manager.run.calls):
            await asyncio.sleep(0.01)
    await manager.cancel("speech-ko")
    assert manager.db.get_install("speech-ko").status == "cancelled"
    assert "speech-ko" not in manager._tasks


async def test_one_install_at_a_time(env):
    manager = env(commands=Commands(hang_on="uv venv"))
    manager.install("speech-ko")
    with pytest.raises(PackError):
        manager.install("speech-ko")
    await manager.cancel("speech-ko")


async def test_remove_deletes_only_what_the_install_recorded(env):
    manager = env()
    manager.install("speech-ko")
    await finished(manager)
    directory = pack_dir(manager.settings, "speech-ko")
    keep = directory / "mine.txt"
    keep.write_text("not the install's")
    manager.remove("speech-ko")
    assert manager.db.get_install("speech-ko") is None
    assert keep.is_file()
    assert not (directory / "models").exists()
    keep.unlink()


async def test_remove_clears_the_folder_of_a_failed_install(env):
    manager = env(hub=Hub(stop_after=5000))
    manager.install("speech-ko")
    await finished(manager)
    manager.remove("speech-ko")
    assert not pack_dir(manager.settings, "speech-ko").exists()


async def test_remove_refuses_a_path_outside_the_folder(env):
    manager = env()
    manager.db.save_install("speech-ko", version="1.0.0", status="failed", files=["../other"])
    with pytest.raises(PackError):
        manager.remove("speech-ko")


async def test_a_restart_marks_a_running_install_failed(env):
    manager = env()
    manager.db.save_install("speech-ko", version="1.0.0", status="installing", stage="downloading")
    manager.start()
    row = manager.db.get_install("speech-ko")
    assert (row.status, row.stage, row.error) == ("failed", None, "interrupted by restart")


async def test_an_older_version_is_not_installed(env):
    manager = env()
    manager.db.save_install("speech-ko", version="0.9.0", status="installed")
    assert not manager.is_installed("speech-ko")


async def test_download_restarts_when_the_server_ignores_range(tmp_path):
    dest = tmp_path / "file.bin"
    (tmp_path / "file.bin.part").write_bytes(MODEL[:100])
    hub = Hub(ignore_range=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(hub)) as client:
        await download(client, "https://huggingface.co/a", dest, len(MODEL), sha(MODEL))
    assert dest.read_bytes() == MODEL


async def test_download_keeps_a_right_file_and_replaces_a_wrong_one(tmp_path):
    dest = tmp_path / "file.bin"
    dest.write_bytes(MODEL)
    hub = Hub()
    async with httpx.AsyncClient(transport=httpx.MockTransport(hub)) as client:
        await download(client, "https://huggingface.co/a", dest, len(MODEL), sha(MODEL))
        assert hub.ranges == []
        dest.write_bytes(b"y" * len(MODEL))
        await download(client, "https://huggingface.co/a", dest, len(MODEL), sha(MODEL))
    assert dest.read_bytes() == MODEL


async def test_download_reports_short_and_refused_files(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))) as client:
        with pytest.raises(DownloadError):
            await download(client, "https://huggingface.co/a", tmp_path / "a", 10, sha(b""))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=httpx.ByteStream(b"abc")))
    ) as client:
        with pytest.raises(DownloadError) as e:
            await download(client, "https://huggingface.co/a", tmp_path / "b", 10, sha(b""))
    assert not isinstance(e.value, ChecksumError)
