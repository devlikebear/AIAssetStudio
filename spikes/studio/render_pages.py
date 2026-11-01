# Spike of 2026-11-01 (docs/plans/notes/studio-spike-2026-11-01.md). Kept as a reference, not run by the app.
"""Render storybook pages with Qwen-Image-2.1 + Viggle Turbo through ComfyUI, one or two character references."""
import os
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from aiassetstudio.comfy.client import ComfyClient  # noqa: E402
from aiassetstudio.comfy.graphs import QWEN_OUTPUT_NODE, Reference, qwen_t2i_turbo, qwen_text_encode  # noqa: E402

ROOT = Path(os.environ["SPIKE_BOOK_DIR"])  # holds storyboard.json, pages/, refs/; never commit a work's text
W, H = 1184, 880
ORDINAL = ["first", "second"]


def page_prompt(book, page):
    names = page["refs"]
    lines = []
    for i, name in enumerate(names):
        lines.append(f"The {ORDINAL[i]} reference image shows the character design of {book['characters'][name]}.")
    if names:
        lines.append("Keep each character's face, hair and clothing exactly as in the references, in a natural new pose.")
    for name in page["cast"]:
        if name not in names:
            lines.append(book["characters"][name] + ".")
    lines.append(page["prompt"])
    lines.append(book["style"])
    return " ".join(lines)


def add_second_ref(graph, name):
    encode = graph["5"]["inputs"]
    graph["21"] = {"class_type": "LoadImage", "inputs": {"image": name}}
    graph["22"] = {"class_type": "JoinImageWithAlpha", "inputs": {"image": ["21", 0], "alpha": ["21", 1]}}
    encode["images.image_2"] = ["22", 0]


async def render(client, book, page, seed, suffix=""):
    uploaded = []
    for name in page["refs"]:
        uploaded.append(await client.upload_image(ROOT / "refs" / f"{name}.png", f"lw_{name}.png", "studio_spike"))
    ref = Reference(uploaded[0], "latent") if uploaded else None
    prompt = page_prompt(book, page)
    prefix = f"studio_spike/p{page['n']:02d}_{seed}"

    t0 = time.monotonic()
    encode = qwen_text_encode(prompt, ref)
    if len(uploaded) > 1:
        add_second_ref(encode, uploaded[1])
    encode_id = str(uuid.uuid4())
    await client.submit(encode, prompt_id=encode_id)
    await client.free(unload_models=True, free_memory=False)
    await client.wait(encode_id, timeout=900)
    t1 = time.monotonic()

    graph = qwen_t2i_turbo(prompt, seed, prefix, W, H, ref=ref, cache_cpu=bool(uploaded))
    if len(uploaded) > 1:
        add_second_ref(graph, uploaded[1])
    gen_id = str(uuid.uuid4())
    await client.submit(graph, prompt_id=gen_id)
    entry = await client.wait(gen_id, timeout=900)
    t2 = time.monotonic()

    stats = await client.system_stats()
    files = entry["outputs"][QWEN_OUTPUT_NODE]["images"]
    data = await client.fetch_output(files[0]["filename"], files[0]["subfolder"])
    out = ROOT / "pages" / f"p{page['n']:02d}{suffix}.png"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(data)
    device = stats["devices"][0]
    rec = {
        "page": page["n"], "seed": seed, "refs": page["refs"], "file": out.name,
        "encode_s": round(t1 - t0, 1), "draw_s": round(t2 - t1, 1), "total_s": round(t2 - t0, 1),
        "vram_free_mb": round(device["vram_free"] / 2**20), "ram_free_mb": round(stats["system"]["ram_free"] / 2**20),
    }
    with (ROOT / "render_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False), flush=True)


async def main():
    book = json.loads((ROOT / "storyboard.json").read_text(encoding="utf-8"))
    wanted = {int(a) for a in sys.argv[1:] if not a.startswith("seed=")} or {p["n"] for p in book["pages"]}
    offset = next((int(a[5:]) for a in sys.argv[1:] if a.startswith("seed=")), 0)
    client = ComfyClient("http://127.0.0.1:8188")
    try:
        for page in book["pages"]:
            if page["n"] in wanted:
                await render(client, book, page, 7000 + page["n"] + offset, f"_s{offset}" if offset else "")
    finally:
        await client.aclose()


asyncio.run(main())
