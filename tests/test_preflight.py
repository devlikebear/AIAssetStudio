import pytest
from fakes import ALL_MODELS, ALL_NODES, FakeComfy

from aiassetstudio.comfy.client import ComfyClient
from aiassetstudio.comfy.graphs import QWEN_BOOK_UNET, YUE2_CKPT
from aiassetstudio.comfy.preflight import check


async def run_check(fake: FakeComfy):
    client = ComfyClient("http://comfy.test", transport=fake.transport)
    try:
        return await check(client)
    finally:
        await client.aclose()


async def test_all_present():
    result = await run_check(FakeComfy())
    assert result["qwen_turbo"].ok
    assert result["qwen_turbo"].missing_nodes == []
    assert result["qwen_turbo"].missing_models == []


async def test_missing_node():
    result = await run_check(FakeComfy(nodes=ALL_NODES - {"ManualSigmas", "QwenImage21Cache"}))
    assert not result["qwen_turbo"].ok
    assert result["qwen_turbo"].missing_nodes == ["ManualSigmas", "QwenImage21Cache"]
    assert result["qwen_turbo"].missing_models == []


@pytest.mark.parametrize("drop_folder", [False, True])
async def test_missing_model(drop_folder):
    models = {k: set(v) for k, v in ALL_MODELS.items()}
    if drop_folder:
        del models["diffusion_models"]  # ComfyUI answers 404 for an unknown folder type
    else:
        models["diffusion_models"].discard(QWEN_BOOK_UNET)
    result = await run_check(FakeComfy(models=models))
    assert not result["qwen_turbo"].ok
    assert result["qwen_turbo"].missing_models == [f"diffusion_models/{QWEN_BOOK_UNET}"]


async def test_comfyui_down():
    result = await run_check(FakeComfy(down=True))
    assert not result["qwen_turbo"].ok
    assert result["qwen_turbo"].reason == "comfyui_down"


async def test_music_families():
    result = await run_check(FakeComfy())
    assert result["ace"].ok and result["yue2"].ok
    models = {k: set(v) for k, v in ALL_MODELS.items()}
    del models["checkpoints"]  # YuE2's only folder
    result = await run_check(FakeComfy(models=models, nodes=ALL_NODES - {"YuE2GenerateABC"}))
    assert result["ace"].ok and result["qwen_turbo"].ok
    assert not result["yue2"].ok
    assert result["yue2"].missing_nodes == ["YuE2GenerateABC"]
    assert result["yue2"].missing_models == [f"checkpoints/{YUE2_CKPT}"]
