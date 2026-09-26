"""Does encoding the prompt in a prompt of its own, then unloading the models, keep VAEDecode fast?

vae_decode_test.py showed plain VAEDecode taking 40 s to 6+ min whenever the text encoder ran in the same prompt
(3 of 5 runs), and VAEDecodeTiled leaving visible alpha seams. Here, per case, after a full POST /free:
  1. encode-only prompt: CLIPLoader -> TextEncodeQwenImage21 -> PreviewAny (same node ids/inputs as the full graph)
  2. POST /free {"unload_models": true, "free_memory": false}, sent while step 1 runs, so ComfyUI unloads the
     models and empties the CUDA cache after step 1 but keeps cached node outputs (the conditioning)
  3. two full candidate graphs (plain VAEDecode) that should reuse the cached conditioning
Decode time is read from ComfyUI's log. Run with the backend idle: uv run python spikes/encode_first_test.py
"""

import re
import sys
import time
import uuid
from datetime import datetime

import httpx

from aiassetstudio.comfy.graphs import qwen_t2i_turbo
from aiassetstudio.prompts import build_image_prompt
from aiassetstudio.store.models import Project

BASE = "http://127.0.0.1:8188"
STALL_LIMIT = 120
PROJECT = Project(id=0, slug="spike", name="spike", created_at="", updated_at="")
CASES = [
    ("sprite", "a small green slime monster with big eyes", 8),  # stalled 57 s with plain decode in vae_decode_test
    ("icon", "a steel short sword with a leather-wrapped hilt", 21),
    ("sprite", "a skeleton warrior holding a rusty shield", 33),
]


def encode_only(prompt: str) -> dict:
    full = qwen_t2i_turbo(prompt, 0, "unused")
    return {"3": full["3"], "5": full["5"], "20": {"class_type": "PreviewAny", "inputs": {"source": ["5", 0]}}}


def clean(m: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", m).strip()


def submit_and_wait(c: httpx.Client, graph: dict) -> tuple[str, float, str]:
    pid = str(uuid.uuid4())
    r = c.post("/prompt", json={"prompt": graph, "prompt_id": pid})
    r.raise_for_status()
    return pid, *wait(c, pid)


def wait(c: httpx.Client, pid: str) -> tuple[float, str]:
    t0 = time.monotonic()
    interrupted = False
    while True:
        h = c.get(f"/history/{pid}").json()
        if pid in h:
            return time.monotonic() - t0, h[pid]["status"]["status_str"] + (" (interrupted)" if interrupted else "")
        if not interrupted and time.monotonic() - t0 > STALL_LIMIT:
            c.post("/interrupt", json={"prompt_id": pid})
            interrupted = True
        time.sleep(0.5)


def segments(c: httpx.Client, since: str) -> list[dict]:
    """Split the log after `since` into prompts: TE loaded?, VAE decode seconds, total seconds."""
    out, cur = [], None
    for e in c.get("/internal/logs/raw").json()["entries"]:
        if e["t"] <= since:
            continue
        m = clean(e["m"])
        t = datetime.fromisoformat(e["t"])
        if m.endswith("got prompt"):
            cur = {"te_loaded": False, "vae_at": None, "vae_decode": None}
        elif cur is None:
            continue
        elif "Requested to load QwenImage21TEModel_" in m:
            cur["te_loaded"] = True
        elif "WanVAE prepared" in m:
            cur["vae_at"] = t
        elif "unloaded" in m and "models unloaded" in m:
            cur.setdefault("unloads", []).append(m)
        elif m.startswith("Prompt executed"):
            cur["total"] = float(re.search(r"in ([\d.]+) seconds", m).group(1))
            if cur["vae_at"]:
                cur["vae_decode"] = round((t - cur["vae_at"]).total_seconds(), 2)
            cur.pop("vae_at")
            out.append(cur)
            cur = None
    return out


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=30) as c:
        q = c.get("/queue").json()
        if q["queue_running"] or q["queue_pending"]:
            sys.exit("ComfyUI is busy; not running the experiment")
        for kind, desc, seed in CASES:
            c.post("/free", json={"unload_models": True, "free_memory": True})
            time.sleep(3)
            since = datetime.now().isoformat()
            prompt = build_image_prompt(PROJECT, kind, desc)
            t0 = time.monotonic()
            enc_pid = str(uuid.uuid4())
            c.post("/prompt", json={"prompt": encode_only(prompt), "prompt_id": enc_pid}).raise_for_status()
            c.post("/free", json={"unload_models": True, "free_memory": False})  # applied after the encode prompt
            wait(c, enc_pid)
            walls = []
            for i in range(2):
                _, wall, status = submit_and_wait(c, qwen_t2i_turbo(prompt, seed + i, f"spike_enc/{kind}_{seed + i}"))
                walls.append((round(wall, 1), status))
            total = time.monotonic() - t0
            time.sleep(1)
            print(f"{kind} seed {seed}: job wall {total:.1f} s, candidates {walls}")
            for s in segments(c, since):
                print("   ", s)
        c.post("/free", json={"unload_models": True, "free_memory": True})


if __name__ == "__main__":
    main()
