# Spike of 2026-11-01 (docs/plans/notes/studio-spike-2026-11-01.md). Kept as a reference, not run by the app.
"""Animate storybook pages with Wan 2.2 14B I2V and the 4-step Lightning LoRAs through ComfyUI, measuring time and memory."""
import os
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from aiassetstudio.comfy.client import ComfyClient  # noqa: E402

ROOT = Path(os.environ["SPIKE_BOOK_DIR"])  # holds storyboard.json, pages/, refs/; never commit a work's text
REDONE: set[int] = set()  # pages whose second render was chosen
W, H, FRAMES, FPS = 832, 624, 81, 16
NEG = "text, letters, watermark, subtitles, talking, mouth moving, extra people, deformed hands, flicker, jump cut, blood"
MOTION = {int(k): v for k, v in json.loads((ROOT / "motion.json").read_text(encoding="utf-8")).items()}
STILL = " Everyone stays in exactly the same place facing the same way. Nobody walks, leaves or turns around. Only small natural movement."
MOVING = {4, 5, 10}
LORA_HIGH = "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"
LORA_LOW = "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"


def graph(prompt, image, seed, prefix):
    def n(class_type, **inputs):
        return {"class_type": class_type, "inputs": inputs}

    return {
        "1": n("UNETLoader", unet_name="wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", weight_dtype="default"),
        "2": n("UNETLoader", unet_name="wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors", weight_dtype="default"),
        "3": n("LoraLoaderModelOnly", model=["1", 0], lora_name=LORA_HIGH, strength_model=1.0),
        "4": n("LoraLoaderModelOnly", model=["2", 0], lora_name=LORA_LOW, strength_model=1.0),
        "5": n("ModelSamplingSD3", model=["3", 0], shift=5.0),
        "6": n("ModelSamplingSD3", model=["4", 0], shift=5.0),
        "7": n("CLIPLoader", clip_name="umt5_xxl_fp8_e4m3fn_scaled.safetensors", type="wan", device="default"),
        "8": n("CLIPTextEncode", clip=["7", 0], text=prompt),
        "9": n("CLIPTextEncode", clip=["7", 0], text=NEG),
        "10": n("VAELoader", vae_name="wan_2.1_vae.safetensors"),
        "11": n("LoadImage", image=image),
        "12": n("WanImageToVideo", positive=["8", 0], negative=["9", 0], vae=["10", 0], start_image=["11", 0],
                width=W, height=H, length=FRAMES, batch_size=1),
        "13": n("KSamplerAdvanced", model=["5", 0], add_noise="enable", noise_seed=seed, steps=4, cfg=1.0,
                sampler_name="euler", scheduler="simple", positive=["12", 0], negative=["12", 1],
                latent_image=["12", 2], start_at_step=0, end_at_step=2, return_with_leftover_noise="enable"),
        "14": n("KSamplerAdvanced", model=["6", 0], add_noise="disable", noise_seed=seed, steps=4, cfg=1.0,
                sampler_name="euler", scheduler="simple", positive=["12", 0], negative=["12", 1],
                latent_image=["13", 0], start_at_step=2, end_at_step=10000, return_with_leftover_noise="disable"),
        "15": n("VAEDecode", samples=["14", 0], vae=["10", 0]),
        "16": n("CreateVideo", images=["15", 0], fps=float(FPS)),
        "17": n("SaveVideo", video=["16", 0], filename_prefix=prefix, format="mp4"),
    }


async def watch(client, stop, low):
    while not stop.is_set():
        try:
            s = await client.system_stats(timeout=5.0)
            low["vram"] = min(low["vram"], s["devices"][0]["vram_free"] / 2**30)
            low["ram"] = min(low["ram"], s["system"]["ram_free"] / 2**30)
        except Exception:  # the server can be too busy to answer; a missed sample is fine
            pass
        await asyncio.sleep(3)


async def render(client, n, seed):
    name = f"p{n:02d}_s100.png" if n in REDONE else f"p{n:02d}.png"
    image = await client.upload_image(ROOT / "pages" / name, f"lw_page_{n:02d}.png", "studio_spike")
    # CFG 1 ignores the negative prompt, so the limits on motion have to be stated in the positive one.
    still = "" if n in MOVING else STILL
    prompt = (MOTION[n] + still + " Korean ink wash and watercolor picture book illustration, the painted style stays the same, "
              "gentle natural motion, static composition.")
    stats = await client.system_stats()
    low = {"vram": stats["devices"][0]["vram_free"] / 2**30, "ram": stats["system"]["ram_free"] / 2**30}
    stop = asyncio.Event()
    watcher = asyncio.create_task(watch(client, stop, low))
    t0 = time.monotonic()
    gen_id = str(uuid.uuid4())
    await client.submit(graph(prompt, image, seed, f"studio_spike/v{n:02d}"), prompt_id=gen_id)
    try:
        entry = await client.wait(gen_id, timeout=3000, poll=2.0)
    finally:
        stop.set()
        await watcher
    took = time.monotonic() - t0
    files = next(v for k, v in entry["outputs"]["17"].items() if isinstance(v, list))
    data = await client.fetch_output(files[0]["filename"], files[0].get("subfolder", ""))
    out = ROOT / "video" / f"v{n:02d}.mp4"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(data)
    rec = {"page": n, "seed": seed, "seconds": round(took, 1), "clip_s": round(FRAMES / FPS, 2),
           "lowest_vram_free_gb": round(low["vram"], 2), "lowest_ram_free_gb": round(low["ram"], 2)}
    with (ROOT / "video_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec), flush=True)


async def main():
    client = ComfyClient("http://127.0.0.1:8188")
    try:
        for n in [int(a) for a in sys.argv[1:]]:
            await render(client, n, 9000 + n)
    finally:
        await client.aclose()


asyncio.run(main())
