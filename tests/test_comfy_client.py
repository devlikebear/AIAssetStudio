import io
import uuid

import pytest
from fakes import FakeComfy
from PIL import Image

from aiassetstudio.comfy.client import (
    ComfyClient,
    ComfyExecutionError,
    ComfyPromptError,
    ComfyTimeout,
    ComfyUnavailable,
    output_files,
)
from aiassetstudio.comfy.graphs import QWEN_OUTPUT_NODE, qwen_t2i_turbo


@pytest.fixture
async def make_client():
    clients = []

    def make(fake: FakeComfy) -> ComfyClient:
        client = ComfyClient("http://comfy.test", transport=fake.transport)
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


GRAPH = qwen_t2i_turbo("a slime", seed=1, prefix="t_abc")


async def test_submit_and_wait_success(make_client):
    fake = FakeComfy()
    client = make_client(fake)
    pid = await client.submit(GRAPH)
    assert fake.prompts[pid] == GRAPH
    entry = await client.wait(pid, timeout=1, poll=0.01)
    [image] = output_files(entry, QWEN_OUTPUT_NODE)
    assert image["subfolder"] == "aiassetstudio"
    assert image["filename"].startswith("t_abc_")


async def test_submit_node_errors(make_client):
    client = make_client(FakeComfy(fail_with="node_errors"))
    with pytest.raises(ComfyPromptError) as exc:
        await client.submit(GRAPH)
    assert "5" in exc.value.node_errors
    assert "Value not in list" in str(exc.value)
    assert "TextEncodeQwenImage21" in str(exc.value)


async def test_execution_error(make_client):
    client = make_client(FakeComfy(fail_with="error"))
    pid = await client.submit(GRAPH)
    with pytest.raises(ComfyExecutionError) as exc:
        await client.wait(pid, timeout=1, poll=0.01)
    assert exc.value.exception_type == "torch.OutOfMemoryError"
    assert exc.value.node_type == "SamplerCustomAdvanced"
    assert "CUDA out of memory" in str(exc.value)


async def test_wait_timeout(make_client):
    client = make_client(FakeComfy(fail_with="hang"))
    pid = await client.submit(GRAPH)
    with pytest.raises(ComfyTimeout):
        await client.wait(pid, timeout=0.05, poll=0.01)


async def test_fetch_output(make_client):
    fake = FakeComfy()
    client = make_client(fake)
    data = await client.fetch_output("x_00001_.png", "aiassetstudio")
    img = Image.open(io.BytesIO(data))
    assert img.mode == "RGBA"
    assert img.size == (256, 256)
    assert fake.views == [{"filename": "x_00001_.png", "subfolder": "aiassetstudio", "type": "output"}]


async def test_targeted_interrupt_ends_running_prompt(make_client):
    fake = FakeComfy(fail_with="hang")
    client = make_client(fake)
    pid = await client.submit(GRAPH)
    await client.interrupt("some-other-prompt")  # not running: no effect
    assert pid not in fake.history
    await client.interrupt(pid)
    with pytest.raises(ComfyExecutionError) as exc:
        await client.wait(pid, timeout=1, poll=0.01)
    assert exc.value.exception_type == "interrupted"
    assert fake.interrupts == ["some-other-prompt", pid]


async def test_client_chosen_prompt_id_and_queue_delete(make_client):
    fake = FakeComfy(fail_with="hang")
    client = make_client(fake)
    pid = str(uuid.uuid4())
    assert await client.submit(GRAPH, prompt_id=pid) == pid
    await client.delete_queued([pid])
    assert fake.deleted == [pid]


async def test_upload_image(make_client, tmp_path):
    fake = FakeComfy()
    client = make_client(fake)
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG fake bytes")
    assert await client.upload_image(ref, "ref_demo.png") == "aiassetstudio/ref_demo.png"
    assert fake.uploads == [{"name": "ref_demo.png", "subfolder": "aiassetstudio", "data": b"\x89PNG fake bytes"}]


async def test_free_sends_body(make_client):
    fake = FakeComfy()
    client = make_client(fake)
    await client.free()
    assert fake.free_calls == [{"unload_models": True, "free_memory": True}]


async def test_comfyui_down(make_client):
    client = make_client(FakeComfy(down=True))
    assert await client.is_up() is False
    with pytest.raises(ComfyUnavailable):
        await client.submit(GRAPH)
