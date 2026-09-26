"""Does a transparent style reference keep the generated background transparent? (Phase 3, T3.A.3)

Uploads the reference, then per mode (latent, vision): POST /free, encode-only prompt, unload the models while
keeping the cached conditioning (as the app does), then N candidates with the Viggle Turbo graph. Records per image:
alpha stats of the raw and processed sprite, generation time and peak VRAM (nvidia-smi, polled every 0.5 s).
Run it while nothing else uses ComfyUI:
    uv run python scripts/validate_ref_rgba.py <reference.png> --out <folder>
"""

import argparse
import asyncio
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image

from aiassetstudio.comfy.client import ComfyClient, output_files
from aiassetstudio.comfy.graphs import QWEN_OUTPUT_NODE, Reference, qwen_t2i_turbo, qwen_text_encode
from aiassetstudio.config import load_settings
from aiassetstudio.post.image import alpha_stats, process_image
from aiassetstudio.prompts import RGBA_PREFIX, RGBA_SUFFIX

STYLE_INSTRUCTION = (
    "Use picture 1 only as a style reference for palette, outline, shading and proportions. "
    "Draw a new subject: {subject}."
)
# 2026-09-25: only this edit wording (with mode latent) drew the new subject instead of copying picture 1.
EDIT_INSTRUCTION = (
    "Replace the subject of picture 1 with {subject}. Keep the same art style, palette, outline and shading "
    "as picture 1. Full body, centered, one subject only, no ground, no cast shadow, no text."
)
PIXEL_STYLE = " Pixel art, crisp hard-edged pixels, limited palette, no anti-aliasing."


class VramPeak:
    """Highest `nvidia-smi` memory.used (MiB) seen while the block runs."""

    def __enter__(self):
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
        return self

    def _poll(self):
        while not self._stop.is_set():
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            if out.strip():
                self.peak = max(self.peak, int(out.split()[0]))
            self._stop.wait(0.5)

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


async def run(
    ref_path: Path, out: Path, count: int, modes: list[str], cache_cpu: bool, prompt: str, tag: str
) -> list[dict]:
    settings = load_settings()
    async with httpx.AsyncClient(timeout=5) as http:
        queue = (await http.get(f"{settings.comfy_url}/queue")).json()
    if queue["queue_running"] or queue["queue_pending"]:
        raise SystemExit("ComfyUI is busy; not running the validation")
    out.mkdir(parents=True, exist_ok=True)
    client = ComfyClient(settings.comfy_url)
    ref_name = await client.upload_image(ref_path, "ref_validation.png")
    print(f"reference {ref_path} -> {ref_name}", flush=True)
    results = []
    try:
        for mode in modes:
            ref = Reference(ref_name, mode)
            await client.free()  # cold start per mode: models unloaded, node cache cleared
            await asyncio.sleep(3)  # let ComfyUI apply the flags before the next prompt is queued
            encode_id = str(uuid.uuid4())
            t0 = time.monotonic()
            with VramPeak() as vram:
                await client.submit(qwen_text_encode(prompt, ref), prompt_id=encode_id)
                await client.free(unload_models=True, free_memory=False)
                await client.wait(encode_id, timeout=600)
            print(f"{mode}: encode {time.monotonic() - t0:.1f} s, peak VRAM {vram.peak} MiB", flush=True)
            for i in range(count):
                prompt_id = str(uuid.uuid4())
                t0 = time.monotonic()
                with VramPeak() as vram:
                    graph = qwen_t2i_turbo(
                        prompt, seed=100 + i, prefix=f"ref_validation/{tag}{mode}_{i}", ref=ref, cache_cpu=cache_cpu
                    )
                    await client.submit(graph, prompt_id=prompt_id)
                    entry = await client.wait(prompt_id, timeout=600)
                seconds = time.monotonic() - t0
                [image] = output_files(entry, QWEN_OUTPUT_NODE)
                data = await client.fetch_output(image["filename"], image["subfolder"], image["type"])
                raw_path = out / f"{tag}{mode}_{i}.png"
                raw_path.write_bytes(data)
                raw = Image.open(raw_path)
                processed = process_image(raw, "sprite")
                processed.save(out / f"{tag}{mode}_{i}_processed.png")
                result = {
                    "mode": mode,
                    "seed": 100 + i,
                    "seconds": round(seconds, 1),
                    "peak_vram_mib": vram.peak,
                    "raw_mode": raw.mode,
                    "alpha_raw": alpha_stats(raw),
                    "alpha_processed": alpha_stats(processed),
                    "size_processed": list(processed.size),
                    "file": str(raw_path),
                }
                results.append(result)
                print(json.dumps(result), flush=True)
    finally:
        await client.free()
        await client.aclose()
    (out / f"{tag}results.json").write_text(json.dumps(results, indent=2))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference", type=Path, help="transparent PNG used as the style reference")
    parser.add_argument("--out", type=Path, required=True, help="folder for images and results.json")
    parser.add_argument("--count", type=int, default=2, help="candidates per mode")
    parser.add_argument("--modes", default="latent,vision")
    parser.add_argument("--cache-cpu", action="store_true", help="put QwenImage21Cache(device=cpu) in the graph")
    parser.add_argument("--wording", choices=["style", "edit"], default="style", help="how picture 1 is referred to")
    parser.add_argument("--subject", default="a small slime monster")
    parser.add_argument("--pixel", action="store_true", help="add the pixel-art style phrase")
    parser.add_argument("--tag", default="", help="prefix for output file names")
    args = parser.parse_args()
    instruction = (EDIT_INSTRUCTION if args.wording == "edit" else STYLE_INSTRUCTION).format(subject=args.subject)
    prompt = RGBA_PREFIX + instruction + (PIXEL_STYLE if args.pixel else "") + RGBA_SUFFIX
    print(prompt, flush=True)
    asyncio.run(run(args.reference, args.out, args.count, args.modes.split(","), args.cache_cpu, prompt, args.tag))


if __name__ == "__main__":
    main()
