# Spike of 2026-11-03. Kept as a reference, not run by the app.
"""Can LTX-2.5 make better page clips than Wan 2.2? The same approved pictures and motion through LTX-2.5's distilled
22B model, set beside the Wan clips the book already has.

usage: ltx_compare.py <book id> <out dir> <page>...; run with ComfyUI up and the backend idle. The prompts and pictures
are read from the studio's book, so no work's text is kept here. The graph follows ComfyUI's own template
video_ltx2_5_i2v.json (two stages: 8 steps at half size, x2 latent upscale, 3 steps), without its prompt enhancer.
"""

import asyncio
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from aiassetstudio.book_prompts import clip_prompt  # noqa: E402
from aiassetstudio.comfy.client import ComfyClient  # noqa: E402
from aiassetstudio.config import load_settings  # noqa: E402

UNET = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
TEXT_ENCODER = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
VIDEO_VAE = "ltx-2.5-video-vae-bf16.safetensors"
AUDIO_VAE = "ltx-2.5-audio-vae-bf16.safetensors"
UPSCALER = "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"
WIDTH, HEIGHT, FPS, SECONDS = 1024, 768, 24, 5
FRAMES = SECONDS * FPS + 1
STAGE_1 = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
STAGE_2 = "0.85, 0.7250, 0.4219, 0.0"
NEGATIVE = "pc game, console game, video game, cartoon, childish, ugly"
TIMES = (0, 1.5, 2.5, 3.5, 4.5)


def node(class_type: str, **inputs) -> dict:
    return {"class_type": class_type, "inputs": inputs}


def text_nodes(prompt: str) -> dict:
    return {
        "2": node("CLIPLoader", clip_name=TEXT_ENCODER, type="ltxv", device="default"),
        "3": node("CLIPTextEncode", clip=["2", 0], text=prompt),
        "4": node("CLIPTextEncode", clip=["2", 0], text=NEGATIVE),
    }


def encode_graph(prompt: str) -> dict:
    return text_nodes(prompt) | {
        "40": node("PreviewAny", source=["3", 0]),
        "41": node("PreviewAny", source=["4", 0]),
    }


def clip_graph(prompt: str, image: str, seed: int, prefix: str) -> dict:
    return text_nodes(prompt) | {
        "1": node("UNETLoader", unet_name=UNET, weight_dtype="default"),
        "5": node("LTXVConditioning", positive=["3", 0], negative=["4", 0], frame_rate=float(FPS)),
        "6": node("VAELoader", vae_name=VIDEO_VAE),
        "7": node("VAELoader", vae_name=AUDIO_VAE),
        "8": node("LoadImage", image=image),
        "9": node("LTXVPreprocess", image=["8", 0], img_compression=18),
        "10": node("EmptyLTXVLatentVideo", width=WIDTH // 2, height=HEIGHT // 2, length=FRAMES, batch_size=1),
        "11": node("LTXVImgToVideoInplace", vae=["6", 0], image=["9", 0], latent=["10", 0], strength=0.7, bypass=False),
        "12": node("LTXVEmptyLatentAudio", frames_number=FRAMES, frame_rate=FPS, batch_size=1, audio_vae=["7", 0]),
        "13": node("LTXVConcatAVLatent", video_latent=["11", 0], audio_latent=["12", 0]),
        "14": node("LTXVDualCFGGuider", model=["1", 0], positive=["5", 0], negative=["5", 1], video_cfg=1.0, audio_cfg=1.0),
        "15": node("RandomNoise", noise_seed=seed),
        "16": node("KSamplerSelect", sampler_name="euler_ancestral"),
        "17": node("ManualSigmas", sigmas=STAGE_1),
        "18": node("SamplerCustomAdvanced", noise=["15", 0], guider=["14", 0], sampler=["16", 0], sigmas=["17", 0], latent_image=["13", 0]),
        "19": node("LTXVSeparateAVLatent", av_latent=["18", 0]),
        "20": node("LatentUpscaleModelLoader", model_name=UPSCALER),
        "21": node("LTXVLatentUpsampler", samples=["19", 0], upscale_model=["20", 0], vae=["6", 0]),
        "22": node("LTXVImgToVideoInplace", vae=["6", 0], image=["9", 0], latent=["21", 0], strength=1.0, bypass=False),
        "23": node("LTXVConcatAVLatent", video_latent=["22", 0], audio_latent=["19", 1]),
        "24": node("RandomNoise", noise_seed=seed + 1),
        "25": node("ManualSigmas", sigmas=STAGE_2),
        "26": node("SamplerCustomAdvanced", noise=["24", 0], guider=["14", 0], sampler=["16", 0], sigmas=["25", 0], latent_image=["23", 0]),
        "27": node("LTXVSeparateAVLatent", av_latent=["26", 0]),
        "28": node("VAEDecodeTiled", samples=["27", 0], vae=["6", 0], tile_size=512, overlap=64, temporal_size=64, temporal_overlap=16),
        "29": node("CreateVideo", images=["28", 0], fps=float(FPS)),
        "30": node("SaveVideo", video=["29", 0], filename_prefix=prefix, format="mp4"),
    }


async def lowest_ram(client: ComfyClient, stop: asyncio.Event, low: dict) -> None:
    while not stop.is_set():
        try:
            stats = await client.system_stats(timeout=5.0)
            low["ram"] = min(low["ram"], stats["system"]["ram_free"] / 2**30)
            low["vram"] = min(low["vram"], stats["devices"][0]["vram_free"] / 2**30)
        except Exception:  # a busy server may not answer; a missed sample is fine
            pass
        await asyncio.sleep(3)


def frames_of(video: Path, out: Path, label: str, width: int = 256, height: int = 192) -> Image.Image:
    strip = Image.new("RGB", (width * len(TIMES), height))
    for i, t in enumerate(TIMES):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", str(out)], check=True)
        with Image.open(out) as frame:
            cell = frame.convert("RGB").resize((width, height))
        ImageDraw.Draw(cell).text((4, 4), f"{label} {t}s", fill="yellow")
        strip.paste(cell, (i * width, 0))
    return strip


async def main() -> None:
    book_id, out = sys.argv[1], Path(sys.argv[2])
    pages = [int(n) for n in sys.argv[3:]]
    out.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    api = f"http://{settings.host}:{settings.port}"
    book = httpx.get(f"{api}/api/books/{book_id}", timeout=30).json()
    style = httpx.get(f"{api}/api/projects/{book['project']}", timeout=30).json()["style"]
    client = ComfyClient(settings.comfy_url)
    rows, strips = [], []
    try:
        await client.free()
        for number in pages:
            page = next(p for p in book["pages"] if p["number"] == number)
            picture = next(a for a in page["candidates"] if a["id"] == page["image_asset_id"])
            png = out / f"p{number:02d}.png"
            png.write_bytes(httpx.get(f"{api}{picture['files']['processed']}", timeout=60).content)
            prompt = "Use the provided start image as the first frame. " + clip_prompt(style, page["motion_prompt"], page["motion_still"])
            image = await client.upload_image(png, f"ltx_p{number:02d}.png", "studio_spike")
            stats = await client.system_stats()
            low = {"ram": stats["system"]["ram_free"] / 2**30, "vram": stats["devices"][0]["vram_free"] / 2**30}
            stop = asyncio.Event()
            watcher = asyncio.create_task(lowest_ram(client, stop, low))
            t0 = time.monotonic()
            try:
                encode_id = str(uuid.uuid4())
                await client.submit(encode_graph(prompt), prompt_id=encode_id)
                await client.free(unload_models=True, free_memory=False)
                await client.wait(encode_id, timeout=900)
                t1 = time.monotonic()
                prompt_id = str(uuid.uuid4())
                await client.submit(clip_graph(prompt, image, 9300 + number, f"studio_spike/ltx_p{number:02d}"), prompt_id=prompt_id)
                entry = await client.wait(prompt_id, timeout=3000, poll=2.0)
            finally:
                stop.set()
                await watcher
            took = time.monotonic() - t1
            files = next(v for v in entry["outputs"]["30"].values() if isinstance(v, list))
            video = out / f"ltx_p{number:02d}.mp4"
            video.write_bytes(await client.fetch_output(files[0]["filename"], files[0].get("subfolder", "")))
            row = {
                "page": number,
                "encode_s": round(t1 - t0, 1),
                "generate_s": round(took, 1),
                "lowest_ram_free_gb": round(low["ram"], 2),
                "lowest_vram_free_gb": round(low["vram"], 2),
            }
            rows.append(row)
            print(json.dumps(row), flush=True)
            strips.append(frames_of(video, out / "f.png", f"LTX p{number}"))
            if page["clip_candidates"]:
                wan = out / f"wan_p{number:02d}.mp4"
                wan.write_bytes(httpx.get(f"{api}{page['clip_candidates'][0]['files']['mp4']}", timeout=60).content)
                strips.append(frames_of(wan, out / "f.png", f"Wan p{number}"))
    finally:
        await client.free()
        await client.aclose()
    sheet = Image.new("RGB", (strips[0].width, sum(s.height for s in strips)))
    for i, strip in enumerate(strips):
        sheet.paste(strip, (0, i * strip.height))
    sheet.save(out / "compare.png")
    (out / "rows.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


asyncio.run(main())
