# Spike of 2026-11-02 (T3.B.3). Kept as a reference, not run by the app.
"""Can sprites and icons move from the Viggle LoRA to the official Turbo checkpoint? The same prompts and seeds through
both, cleaned up by the app's own code, with the transparency and pixel-art numbers side by side.

usage: sprite_turbo.py <out dir>; run with ComfyUI up, and the backend idle. Reads the studio's projects, writes nothing
to them.
"""

import asyncio
import io
import json
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from aiassetstudio.comfy.client import ComfyClient, output_files  # noqa: E402
from aiassetstudio.comfy.graphs import (  # noqa: E402
    QWEN_OUTPUT_NODE,
    Reference,
    qwen_book_page,
    qwen_t2i_turbo,
    qwen_text_encode,
)
from aiassetstudio.config import load_settings  # noqa: E402
from aiassetstudio.jobs.runners import IMAGE_SIZE, REFERENCE_MODE, effective_icon_size, pixel_spec  # noqa: E402
from aiassetstudio.post.image import alpha_stats, colors_used, process_image, reference_ground  # noqa: E402
from aiassetstudio.prompts import build_image_prompt  # noqa: E402
from aiassetstudio.store.db import Database  # noqa: E402
from aiassetstudio.store.files import db_path, from_rel  # noqa: E402

CASES = [
    ("lastlight", "sprite", "a skeleton warrior with a shield"),
    ("lastlight", "sprite", "a small lantern keeper in a hooded cloak"),
    ("lastlight", "icon", "a rusty iron sword"),
    ("tangle-jelly", "sprite", "a round jelly creature with a happy face"),
    ("demo", "sprite", "a slime with a tiny crown"),
]
SEEDS = (5101, 5102)
CELL = 256


async def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    db = Database(db_path(settings))
    client = ComfyClient(settings.comfy_url)
    rows, cells = [], []
    try:
        await client.free()
        for slug, kind, description in CASES:
            project = db.get_project(slug)
            pixel = pixel_spec(project, kind)
            icon_size = effective_icon_size(project) if kind == "icon" and pixel is None else None
            ref = None
            if project.reference_image and kind == "sprite":
                path = from_rel(settings, project.reference_image)
                ref = Reference(await client.upload_image(path, f"ref_{slug}.png", "studio_spike"), REFERENCE_MODE)
                if pixel is not None:
                    with Image.open(path) as reference:
                        pixel = replace(pixel, ground=reference_ground(reference, pixel.height))
            prompt = build_image_prompt(project, kind, description, reference=ref is not None)
            encode_id = str(uuid.uuid4())
            await client.submit(qwen_text_encode(prompt, ref), prompt_id=encode_id)
            await client.free(unload_models=True, free_memory=False)
            await client.wait(encode_id, timeout=600)
            for seed in SEEDS:
                row = []
                for model in ("viggle", "turbo"):
                    prefix = f"studio_spike/sprite_{model}_{seed}"
                    if model == "viggle":
                        graph = qwen_t2i_turbo(prompt, seed, prefix, IMAGE_SIZE, IMAGE_SIZE, ref)
                    else:
                        graph = qwen_book_page(prompt, seed, prefix, IMAGE_SIZE, IMAGE_SIZE, [ref] if ref else [])
                    t0 = time.monotonic()
                    prompt_id = str(uuid.uuid4())
                    await client.submit(graph, prompt_id=prompt_id)
                    entry = await client.wait(prompt_id, timeout=600)
                    took = time.monotonic() - t0
                    file = output_files(entry, QWEN_OUTPUT_NODE)[0]
                    data = await client.fetch_output(file["filename"], file["subfolder"])
                    raw = Image.open(io.BytesIO(data))
                    raw.load()
                    fit: dict = {}
                    processed = process_image(raw, kind, pixel=pixel, icon_size=icon_size, report=fit)
                    alpha = alpha_stats(processed)
                    record = {
                        "project": slug,
                        "kind": kind,
                        "description": description,
                        "seed": seed,
                        "model": model,
                        "seconds": round(took, 1),
                        "raw_mode": raw.mode,
                        "alpha": alpha,
                        "fit": fit.get("fit"),
                        "native": fit.get("native_size"),
                        "colors": colors_used(processed) if pixel else None,
                    }
                    rows.append(record)
                    print(json.dumps(record, ensure_ascii=False), flush=True)
                    cell = Image.new("RGBA", (CELL, CELL), (90, 90, 110, 255))
                    scale = CELL / max(processed.size)
                    size = (round(processed.width * scale), round(processed.height * scale))
                    sharp = Image.Resampling.NEAREST if pixel else Image.Resampling.LANCZOS
                    shown = processed.convert("RGBA").resize(size, sharp)
                    cell.alpha_composite(shown, ((CELL - size[0]) // 2, (CELL - size[1]) // 2))
                    ImageDraw.Draw(cell).text((4, 4), f"{slug} {kind} {seed} {model}", fill="yellow")
                    row.append(cell)
                cells.extend(row)
    finally:
        await client.free()
        await client.aclose()
        db.close()
    columns = 4
    sheet = Image.new("RGB", (CELL * columns, CELL * (len(cells) // columns)), "#222")
    for i, cell in enumerate(cells):
        sheet.paste(cell.convert("RGB"), (i % columns * CELL, i // columns * CELL))
    sheet.save(out / "sheet.png")
    (out / "rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


asyncio.run(main())
