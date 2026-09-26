"""Does VAEDecodeTiled avoid the VAE decode stall after a fresh model load?

2026-09-24: with the text encoder (8.9 GB) and Qwen model (6.9 GB) freshly loaded in one prompt, VAEDecode of a
1024x1024 image took 1.2 s, 40.7 s, and once stalled > 6 min (interrupted). Sampling itself stayed at 6-13 s.
This runs each (prompt, seed) twice after POST /free -- plain VAEDecode vs VAEDecodeTiled -- and times the decode
from ComfyUI's log, then compares the two images (same seed -> only the decode differs).
Run with the backend idle: uv run python spikes/vae_decode_test.py
"""

import io
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from aiassetstudio.comfy.graphs import QWEN_OUTPUT_NODE, qwen_t2i_turbo
from aiassetstudio.prompts import build_image_prompt
from aiassetstudio.store.models import Project

BASE = "http://127.0.0.1:8188"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("spike_out")
STALL_LIMIT = 120  # seconds before interrupting a run
PROJECT = Project(id=0, slug="spike", name="spike", created_at="", updated_at="")
CASES = [
    ("icon", "a red health potion in a round glass bottle with a cork, hand-painted fantasy style", 7),
    ("sprite", "a small green slime monster with big eyes", 8),
]


def graph(prompt: str, seed: int, tiled: bool, prefix: str) -> dict:
    g = qwen_t2i_turbo(prompt, seed, prefix)
    if tiled:
        g["8"] = {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["14", 0],
                "vae": ["4", 0],
                "tile_size": 512,
                "overlap": 64,
                "temporal_size": 64,
                "temporal_overlap": 8,
            },
        }
    return g


def log_times(c: httpx.Client, since: str) -> tuple[float | None, float | None]:
    """(vae_decode_seconds, prompt_seconds) from the newest entries of ComfyUI's log after `since`."""
    entries = [e for e in c.get("/internal/logs/raw").json()["entries"] if e["t"] > since]
    staged = [e["t"] for e in entries if "WanVAE prepared" in e["m"]]
    done = [e for e in entries if "Prompt executed" in e["m"]]
    if not staged or not done:
        return None, None
    t_vae = datetime.fromisoformat(staged[-1])
    t_done = datetime.fromisoformat(done[-1]["t"])
    total = float(re.search(r"in ([\d.]+) seconds", re.sub(r"\x1b\[[0-9;]*m", "", done[-1]["m"])).group(1))
    return (t_done - t_vae).total_seconds(), total


def run(c: httpx.Client, kind: str, desc: str, seed: int, tiled: bool) -> dict:
    c.post("/free", json={"unload_models": True, "free_memory": True})
    time.sleep(3)
    since = datetime.now().isoformat()
    pid = str(uuid.uuid4())
    prefix = f"spike_vae/{kind}_{seed}_{'tiled' if tiled else 'plain'}"
    c.post("/prompt", json={"prompt": graph(build_image_prompt(PROJECT, kind, desc), seed, tiled, prefix), "prompt_id": pid})
    t0 = time.monotonic()
    interrupted = False
    while True:
        h = c.get(f"/history/{pid}").json()
        if pid in h:
            break
        if not interrupted and time.monotonic() - t0 > STALL_LIMIT:
            c.post("/interrupt", json={"prompt_id": pid})
            interrupted = True
        time.sleep(1)
    wall = time.monotonic() - t0
    vae_s, total_s = log_times(c, since)
    result = {"kind": kind, "seed": seed, "tiled": tiled, "wall": round(wall, 1), "vae_decode": vae_s, "comfy_total": total_s}
    result["status"] = h[pid]["status"]["status_str"] + (" (interrupted)" if interrupted else "")
    images = h[pid].get("outputs", {}).get(QWEN_OUTPUT_NODE, {}).get("images", [])
    if images:
        im = images[0]
        data = c.get("/view", params={"filename": im["filename"], "subfolder": im["subfolder"], "type": "output"}).content
        path = OUT / f"{kind}_{seed}_{'tiled' if tiled else 'plain'}.png"
        path.write_bytes(data)
        result["file"] = str(path)
    stats = c.get("/system_stats").json()
    result["ram_free_gb"] = round(stats["system"]["ram_free"] / 2**30, 1)
    print(result, flush=True)
    return result


def compare(a: Path, b: Path) -> str:
    x = np.asarray(Image.open(a).convert("RGBA")).astype(np.int16)
    y = np.asarray(Image.open(b).convert("RGBA")).astype(np.int16)
    d = np.abs(x - y)
    return f"max diff rgb={d[..., :3].max()} alpha={d[..., 3].max()}, mean diff rgb={d[..., :3].mean():.3f} alpha={d[..., 3].mean():.3f}"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=BASE, timeout=30) as c:
        q = c.get("/queue").json()
        if q["queue_running"] or q["queue_pending"]:
            sys.exit("ComfyUI is busy; not running the experiment")
        results = []
        for kind, desc, seed in CASES:
            for tiled in (True, False):
                results.append(run(c, kind, desc, seed, tiled))
        c.post("/free", json={"unload_models": True, "free_memory": True})
    for kind, _, seed in CASES:
        a, b = OUT / f"{kind}_{seed}_tiled.png", OUT / f"{kind}_{seed}_plain.png"
        if a.exists() and b.exists():
            print(f"{kind} seed {seed}: tiled vs plain {compare(a, b)}")


if __name__ == "__main__":
    main()
