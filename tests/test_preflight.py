import pytest
from fakes import ALL_MODELS, ALL_NODES, FakeComfy

from aiassetstudio.comfy.client import ComfyClient
from aiassetstudio.comfy.graphs import VIGGLE_LORA, YUE2_CKPT
from aiassetstudio.comfy.preflight import check


async def run_check(fake: FakeComfy):
    client = ComfyClient("http://comfy.test", transport=fake.transport)
    try:
        return await check(client)
    finally:
        await client.aclose()


async def test_all_present():
    result = await run_check(FakeComfy())
    assert result["qwen"].ok
    assert result["qwen"].missing_nodes == []
    assert result["qwen"].missing_models == []


async def test_missing_node():
    result = await run_check(FakeComfy(nodes=ALL_NODES - {"ViggleTurboLora", "ViggleTurboSigmas"}))
    assert not result["qwen"].ok
    assert result["qwen"].missing_nodes == ["ViggleTurboLora", "ViggleTurboSigmas"]
    assert result["qwen"].missing_models == []


@pytest.mark.parametrize("drop_folder", [False, True])
async def test_missing_model(drop_folder):
    models = {k: set(v) for k, v in ALL_MODELS.items()}
    if drop_folder:
        del models["loras"]  # ComfyUI answers 404 for an unknown folder type
    else:
        models["loras"].discard(VIGGLE_LORA)
    result = await run_check(FakeComfy(models=models))
    assert not result["qwen"].ok
    assert result["qwen"].missing_models == [f"loras/{VIGGLE_LORA}"]


async def test_comfyui_down():
    result = await run_check(FakeComfy(down=True))
    assert not result["qwen"].ok
    assert result["qwen"].reason == "comfyui_down"


async def test_music_families():
    result = await run_check(FakeComfy())
    assert result["ace"].ok and result["yue2"].ok
    models = {k: set(v) for k, v in ALL_MODELS.items()}
    del models["checkpoints"]  # YuE2's only folder
    result = await run_check(FakeComfy(models=models, nodes=ALL_NODES - {"YuE2GenerateABC"}))
    assert result["ace"].ok and result["qwen"].ok
    assert not result["yue2"].ok
    assert result["yue2"].missing_nodes == ["YuE2GenerateABC"]
    assert result["yue2"].missing_models == [f"checkpoints/{YUE2_CKPT}"]
