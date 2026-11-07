import asyncio
import hashlib
from pathlib import Path

import httpx
import pytest

from aiassetstudio.config import Settings, comfy_is_external, resolve_comfy
from aiassetstudio.packs.catalog import GitSource, Measured, PackFile, PackLicense, PackSpec
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


def license_of(pack_id: str = "x") -> PackLicense:
    return PackLicense(
        id="apache-2.0", name="Apache", class_="open", url=LICENSE_URL, sha256=sha(LICENSE), summary_ko="x"
    )


def model_pack(data: bytes = MODEL) -> PackSpec:
    return PackSpec(
        id="video-wan22",
        title="v",
        feature="video",
        version="1.0.0",
        engine="comfy_models",
        licenses=[license_of()],
        files=[
            PackFile(repo="a/b", revision=REVISION, path="m.bin", dest="loras/m.bin", size=len(data), sha256=sha(data))
        ],
        tested=Measured(vram_gb=16, ram_gb=32, disk_gb=1, os="Windows 11"),
    )


def engine_pack() -> PackSpec:
    return PackSpec(
        id="engine-comfyui",
        title="e",
        feature="engine",
        version="0.37.0",
        engine="comfy_engine",
        licenses=[license_of()],
        git=GitSource(url="https://github.com/comfyanonymous/ComfyUI", tag="v0.37.0"),
        python="3.13",
        torch_index="https://download.pytorch.org/whl/cu130",
        torch_packages=["torch==1+cu130"],
        tested=Measured(vram_gb=16, ram_gb=32, disk_gb=1, os="Windows 11"),
    )


@pytest.fixture
def comfy(tmp_path):
    """Settings with a ComfyUI this app did not install."""
    folder = tmp_path / "ComfyUI"
    (folder / "models" / "loras").mkdir(parents=True)
    (folder / "main.py").write_text("")
    return Settings(data_dir=tmp_path / "data", comfy_dir=folder)


def manager_for(settings, tmp_path, pack, hub=None, commands=None) -> PackManager:
    db = Database(tmp_path / "packs.db")
    accept(db, pack, ["apache-2.0"])
    return PackManager(
        settings,
        db,
        catalog={pack.id: pack},
        transport=httpx.MockTransport(hub or Hub()),
        run=commands or Commands(),
        disk_free=lambda path: 10 * 2**30,
    )


async def test_a_model_pack_goes_into_comfyui_and_comes_out_again(comfy, tmp_path):
    pack = model_pack()
    manager = manager_for(comfy, tmp_path, pack)
    manager.install(pack.id)
    row = await finished(manager, pack.id)
    assert row.status == "installed", row.error
    dest = comfy.comfy_dir / "models/loras/m.bin"
    assert dest.read_bytes() == MODEL
    assert manager.adopted(pack) == []
    manager.remove(pack.id)
    assert not dest.exists()
    assert (comfy.comfy_dir / "models/loras").is_dir()  # ComfyUI's own folder stays
    manager.db.close()


async def test_a_file_already_in_place_is_adopted_and_stays(comfy, tmp_path):
    pack = model_pack()
    dest = comfy.comfy_dir / "models/loras/m.bin"
    dest.write_bytes(MODEL)
    hub = Hub()
    manager = manager_for(comfy, tmp_path, pack, hub)
    manager.install(pack.id)
    row = await finished(manager, pack.id)
    assert row.status == "installed", row.error
    assert hub.ranges == []
    assert row.files == []
    assert manager.adopted(pack) == ["loras/m.bin"]
    manager.remove(pack.id)
    assert dest.read_bytes() == MODEL
    manager.db.close()


async def test_a_different_file_in_the_way_is_never_replaced(comfy, tmp_path):
    pack = model_pack()
    dest = comfy.comfy_dir / "models/loras/m.bin"
    dest.write_bytes(b"mine")
    manager = manager_for(comfy, tmp_path, pack)
    manager.install(pack.id)
    row = await finished(manager, pack.id)
    assert row.status == "failed"
    assert "will not replace" in row.error
    assert dest.read_bytes() == b"mine"
    manager.remove(pack.id)
    assert dest.read_bytes() == b"mine"
    manager.db.close()


async def test_an_external_comfyui_needs_no_engine_pack(comfy, tmp_path):
    pack = engine_pack()
    commands = Commands()
    manager = manager_for(comfy, tmp_path, pack, commands=commands)
    assert manager.is_external(pack)
    assert resolve_comfy(comfy) == comfy.comfy_dir
    with pytest.raises(PackError, match="needs no engine pack"):
        manager.install(pack.id)
    assert commands.calls == []
    assert sorted(p.name for p in comfy.comfy_dir.iterdir()) == ["main.py", "models"]
    manager.db.close()


async def test_a_model_pack_needs_a_comfyui(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", comfy_dir=tmp_path / "none")
    pack = model_pack()
    manager = manager_for(settings, tmp_path, pack)
    with pytest.raises(PackError, match="install the engine pack first"):
        manager.install(pack.id)
    manager.db.close()


class FakeGit(Commands):
    async def __call__(self, args, cwd, log_path, env):
        if args[:2] == ["git", "clone"]:
            target = cwd / args[-1]
            (target / ".git").mkdir(parents=True)
            read_only = target / ".git" / "object"
            read_only.write_text("x")
            read_only.chmod(0o444)
            (target / "main.py").write_text("")
        return await super().__call__(args, cwd, log_path, env)


async def test_the_engine_pack_clones_its_tag_and_is_then_the_comfyui(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", comfy_dir=tmp_path / "none")
    pack = engine_pack()
    commands = FakeGit()
    manager = manager_for(settings, tmp_path, pack, commands=commands)
    assert not comfy_is_external(settings)
    manager.install(pack.id)
    row = await finished(manager, pack.id)
    assert row.status == "installed", row.error
    clone = commands.calls[0]
    assert clone[:2] == ["git", "clone"]
    assert clone[clone.index("--branch") + 1] == "v0.37.0"
    assert ["-r", "requirements.txt"] == commands.calls[2][-2:]
    assert commands.calls[-1][0].endswith("python.exe") or commands.calls[-1][0].endswith("python")
    engine = pack_dir(settings, pack.id) / "ComfyUI"
    assert resolve_comfy(settings) == engine
    assert ".venv" in commands.calls[-1][0]

    manager.remove(pack.id)
    assert not pack_dir(settings, pack.id).exists()
    assert resolve_comfy(settings) == settings.comfy_dir
    manager.db.close()


async def test_the_engine_stays_while_model_packs_are_inside_it(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", comfy_dir=tmp_path / "none")
    engine, models = engine_pack(), model_pack()
    db = Database(tmp_path / "packs.db")
    manager = PackManager(settings, db, catalog={engine.id: engine, models.id: models}, run=Commands())
    db.save_install(engine.id, version="0.37.0", status="installed", files=["ComfyUI"])
    db.save_install(models.id, version="1.0.0", status="installed", files=["loras/m.bin"])
    with pytest.raises(PackError, match="remove them first"):
        manager.remove(engine.id)
    db.close()
