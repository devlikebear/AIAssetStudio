import asyncio

import pytest

from aiassetstudio.comfy.client import ComfyUnavailable
from aiassetstudio.comfy.launcher import ComfyLauncher
from aiassetstudio.config import Settings


class FakeComfyProcess:
    """Stands in for both the ComfyUI client (is_up) and spawn_detached (start)."""

    def __init__(self, up: bool = False, comes_up: bool = True):
        self.up = up
        self.comes_up = comes_up
        self.launches: list[tuple[list, dict]] = []

    async def is_up(self) -> bool:
        return self.up

    def spawn(self, args, **kwargs):
        self.launches.append((args, kwargs))
        self.up = self.comes_up


def comfy_dir(tmp_path, installed=True):
    root = tmp_path / "ComfyUI"
    if installed:
        (root / ".venv" / "Scripts").mkdir(parents=True)
        (root / ".venv" / "Scripts" / "python.exe").touch()
        (root / "main.py").touch()
    return root


def launcher(tmp_path, fake, installed=True, timeout=1.0):
    settings = Settings(data_dir=tmp_path / "data", comfy_dir=comfy_dir(tmp_path, installed))
    return ComfyLauncher(settings, fake, spawn=fake.spawn, timeout=timeout, interval=0.01)


async def test_already_up(tmp_path):
    fake = FakeComfyProcess(up=True)
    await launcher(tmp_path, fake).ensure()
    assert fake.launches == []


async def test_starts_comfyui_detached(tmp_path):
    fake = FakeComfyProcess()
    ln = launcher(tmp_path, fake)
    await asyncio.gather(ln.ensure(), ln.ensure())  # two callers, one launch
    [(args, kwargs)] = fake.launches
    assert args == [str(tmp_path / "ComfyUI" / ".venv" / "Scripts" / "python.exe"), "main.py", "--port", "8188"]
    assert kwargs == {"cwd": tmp_path / "ComfyUI", "log_path": tmp_path / "data" / "logs" / "comfyui.log"}
    assert ln.log_path == kwargs["log_path"]


async def test_starts_comfyui_with_the_set_python(tmp_path):
    # The portable build: ComfyUI\main.py, with its Python in ..\python_embeded (AIAS_COMFY_PYTHON).
    python = tmp_path / "python_embeded" / "python.exe"
    python.parent.mkdir()
    python.touch()
    root = comfy_dir(tmp_path, installed=False)
    root.mkdir()
    (root / "main.py").touch()
    fake = FakeComfyProcess()
    settings = Settings(data_dir=tmp_path / "data", comfy_dir=root, comfy_python=str(python))
    await ComfyLauncher(settings, fake, spawn=fake.spawn, timeout=1.0, interval=0.01).ensure()
    [(args, kwargs)] = fake.launches
    assert args == [str(python), "main.py", "--port", "8188"]
    assert kwargs["cwd"] == root


async def test_timeout(tmp_path):
    fake = FakeComfyProcess(comes_up=False)
    with pytest.raises(ComfyUnavailable, match="did not start within 0.05 s") as exc:
        await launcher(tmp_path, fake, timeout=0.05).ensure()
    assert "comfyui.log" in str(exc.value)
    assert len(fake.launches) == 1


async def test_not_installed(tmp_path):
    fake = FakeComfyProcess()
    with pytest.raises(ComfyUnavailable, match="ComfyUI not found") as exc:
        await launcher(tmp_path, fake, installed=False).ensure()
    assert "AIAS_COMFY_DIR" in str(exc.value) and "AIAS_COMFY_PYTHON" in str(exc.value)
    assert fake.launches == []
