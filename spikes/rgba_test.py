"""Check whether Qwen-Image-2.1 text-to-image produces real transparent (RGBA) PNGs through ComfyUI's API."""
import json
import os
import time
import urllib.request

import numpy as np
from PIL import Image

BASE = "http://127.0.0.1:8188"
# ComfyUI's output folder, for printing result paths: AIAS_COMFY_DIR, else the ComfyUI folder next to this repository.
COMFY_DIR = os.environ.get("AIAS_COMFY_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ComfyUI")
OUT = os.path.normpath(os.path.join(COMFY_DIR, "output"))
SEED = 42

# Official prompt format from the Qwen-Image-2.1 model card for transparent images.
RGBA_PREFIX = "This is an RGBA image with transparency. "
RGBA_SUFFIX = " The image has alpha channel and the background is transparent."
PROMPTS = {
    "sprite": "A 16-bit pixel art sprite of a small ninja character for a top-down RPG, front view, full body, crisp hard-edged pixels, limited palette.",
    "icon": "A game item icon of a red health potion in a round glass bottle with a cork, hand-painted fantasy style, centered.",
}


def post(path, data):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode()[:3000])
        raise


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path).read())


def graph(prompt, prefix, turbo):
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "5": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["3", 0], "prompt": prompt, "negative_prompt": "", "resolution": 1024}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }
    if turbo:
        g["2"] = {"class_type": "ViggleTurboLora", "inputs": {"model": ["1", 0], "lora_name": "Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-lora-r128.safetensors", "strength": 1.0}}
        g["10"] = {"class_type": "BasicGuider", "inputs": {"model": ["2", 0], "conditioning": ["5", 0]}}
        g["11"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": SEED}}
        g["12"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}}
        g["13"] = {"class_type": "ViggleTurboSigmas", "inputs": {"latent": ["6", 0], "nodes": "1.0, 0.9375, 0.875, 0.75, 0.5, 0.25"}}
        g["14"] = {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["11", 0], "guider": ["10", 0], "sampler": ["12", 0], "sigmas": ["13", 0], "latent_image": ["6", 0]}}
        g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["4", 0]}}
    else:
        g["7"] = {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["5", 0], "negative": ["5", 1], "latent_image": ["6", 0],
                                                       "seed": SEED, "steps": 25, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
        g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["4", 0]}}
    return g


def run(g, label):
    t0 = time.time()
    pid = post("/prompt", {"prompt": g})["prompt_id"]
    while True:
        h = get("/history/" + pid)
        if pid in h and h[pid]["status"].get("completed") is not None:
            break
        time.sleep(1)
    h = h[pid]
    print(f"{label}: {h['status']['status_str']} {time.time() - t0:.1f}s", flush=True)
    for m in h["status"]["messages"]:
        if m[0] == "execution_error":
            print("  ERROR:", m[1].get("exception_type"), str(m[1].get("exception_message"))[:800])
    files = []
    for out in h.get("outputs", {}).values():
        for im in out.get("images", []):
            files.append(os.path.join(OUT, im["subfolder"], im["filename"]))
    return files


def alpha_report(path):
    im = Image.open(path)
    print(f"  {os.path.basename(path)}: mode={im.mode} size={im.size}")
    if im.mode != "RGBA":
        return
    a = np.asarray(im)[..., 3]
    n = a.size
    print(f"  alpha: transparent(0)={np.sum(a == 0) / n:.1%} opaque(255)={np.sum(a == 255) / n:.1%} "
          f"partial={np.sum((a > 0) & (a < 255)) / n:.1%} min={a.min()} max={a.max()}")


jobs = [
    ("sprite", True, "aiassetstudio_test/rgba_sprite_turbo6"),
    ("sprite", False, "aiassetstudio_test/rgba_sprite_base25"),
    ("icon", True, "aiassetstudio_test/rgba_icon_turbo6"),
]
for key, turbo, prefix in jobs:
    prompt = RGBA_PREFIX + PROMPTS[key] + RGBA_SUFFIX
    for f in run(graph(prompt, prefix, turbo), f"{key} {'turbo 6' if turbo else 'base 25'} steps"):
        alpha_report(f)
