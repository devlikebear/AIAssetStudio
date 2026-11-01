"""Does a place picture work as a third reference? T1.A.2 of docs/plans/studio-phase-1-picturebook.md.

usage: three_refs.py <prompt.txt> <out dir> <reference image>... (2 or 3 references); run with ComfyUI up.
The prompt stays outside the repository: it holds a work's text.
"""

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from aiassetstudio.comfy.client import ComfyClient  # noqa: E402
from aiassetstudio.comfy.graphs import QWEN_OUTPUT_NODE, Reference, qwen_t2i_turbo, qwen_text_encode  # noqa: E402

W, H = 1184, 880
SEEDS = (8101, 8102, 8103)


def add_ref(graph: dict, index: int, name: str) -> None:
    load, join = f"3{index}", f"4{index}"
    graph[load] = {"class_type": "LoadImage", "inputs": {"image": name}}
    graph[join] = {"class_type": "JoinImageWithAlpha", "inputs": {"image": [load, 0], "alpha": [load, 1]}}
    graph["5"]["inputs"][f"images.image_{index}"] = [join, 0]


async def watch(client: ComfyClient, stop: asyncio.Event, low: dict) -> None:
    while not stop.is_set():
        try:
            stats = await client.system_stats(timeout=5.0)
            low["vram"] = min(low["vram"], stats["devices"][0]["vram_free"] / 2**30)
            low["ram"] = min(low["ram"], stats["system"]["ram_free"] / 2**30)
        except Exception:  # a busy server may not answer; a missed sample is fine
            pass
        await asyncio.sleep(1)


async def main() -> None:
    prompt = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    client = ComfyClient("http://127.0.0.1:8188")
    try:
        names = [await client.upload_image(Path(p), f"threeref_{i}.png", "studio_spike") for i, p in enumerate(sys.argv[3:])]
        ref = Reference(names[0], "latent")
        for seed in SEEDS:
            low = {"vram": 99.0, "ram": 99.0}
            stop = asyncio.Event()
            watcher = asyncio.create_task(watch(client, stop, low))
            t0 = time.monotonic()
            encode = qwen_text_encode(prompt, ref)
            for i, name in enumerate(names[1:], 2):
                add_ref(encode, i, name)
            encode_id = str(uuid.uuid4())
            await client.submit(encode, prompt_id=encode_id)
            await client.free(unload_models=True, free_memory=False)
            await client.wait(encode_id, timeout=600)
            t1 = time.monotonic()
            graph = qwen_t2i_turbo(prompt, seed, f"studio_spike/three_{seed}", W, H, ref=ref, cache_cpu=True)
            for i, name in enumerate(names[1:], 2):
                add_ref(graph, i, name)
            gen_id = str(uuid.uuid4())
            await client.submit(graph, prompt_id=gen_id)
            entry = await client.wait(gen_id, timeout=600)
            t2 = time.monotonic()
            stop.set()
            await watcher
            file = entry["outputs"][QWEN_OUTPUT_NODE]["images"][0]
            (out / f"{len(names)}refs_{seed}.png").write_bytes(await client.fetch_output(file["filename"], file["subfolder"]))
            print(json.dumps({
                "refs": len(names), "seed": seed, "encode_s": round(t1 - t0, 1), "draw_s": round(t2 - t1, 1),
                "lowest_vram_free_gb": round(low["vram"], 2), "lowest_ram_free_gb": round(low["ram"], 2),
            }), flush=True)
    finally:
        await client.aclose()


asyncio.run(main())
