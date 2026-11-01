import socket
import sys
from pathlib import Path

import pytest

from aiassetstudio.config import Settings
from aiassetstudio.packs.catalog import load_catalog
from aiassetstudio.packs.sidecar import SidecarError, SidecarManager

FAKE = str(Path(__file__).parent / "fake_tts_server.py")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def sidecar(tmp_path):
    manager = SidecarManager(
        Settings(data_dir=tmp_path / "data"),
        None,
        port=free_port(),
        command=[sys.executable, FAKE],
        start_timeout=20,
        interval=0.05,
    )
    yield manager
    await manager.aclose()


async def test_ensure_starts_it_once_and_stop_ends_it(sidecar):
    assert not await sidecar.is_up()
    await sidecar.ensure()
    process = sidecar._process
    assert await sidecar.is_up()
    await sidecar.ensure()
    assert sidecar._process is process
    answer = await sidecar.speak({"text": "말"}, timeout=5)
    assert answer["spoke"] == "말"
    await sidecar.stop()
    assert process.returncode is not None
    assert not sidecar.running
    await sidecar.stop()


async def test_it_starts_again_after_it_stopped(sidecar):
    await sidecar.ensure()
    sidecar._process.kill()
    await sidecar._process.wait()
    await sidecar.ensure()
    assert await sidecar.is_up()


async def test_a_server_that_dies_while_starting_is_reported(sidecar, monkeypatch):
    monkeypatch.setenv("FAKE_TTS_EXIT", "1")
    with pytest.raises(SidecarError, match="stopped while starting"):
        await sidecar.ensure()


async def test_a_server_that_never_gets_ready_is_stopped(tmp_path):
    never = "import sys, time\ntime.sleep(60)\n"
    (tmp_path / "never.py").write_text(never, encoding="utf-8")
    manager = SidecarManager(
        Settings(data_dir=tmp_path / "data"),
        None,
        port=free_port(),
        command=[sys.executable, str(tmp_path / "never.py")],
        start_timeout=0.2,
        interval=0.05,
    )
    with pytest.raises(SidecarError, match="did not start"):
        await manager.ensure()
    assert not manager.running
    await manager.aclose()


async def test_a_pack_that_is_not_installed_is_reported(tmp_path):
    manager = SidecarManager(Settings(data_dir=tmp_path / "data"), load_catalog()["speech-ko"], port=free_port())
    with pytest.raises(SidecarError, match="not installed"):
        await manager.ensure()
    await manager.aclose()


async def test_speak_reports_a_server_that_is_gone(sidecar):
    with pytest.raises(SidecarError, match="did not answer"):
        await sidecar.speak({"text": "말"}, timeout=1)
