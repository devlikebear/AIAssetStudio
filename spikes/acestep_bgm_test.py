"""Check whether ACE-Step 1.5 (via the local ComfyUI API) makes vocal-free game BGM.

Mirrors the 'Text to Audio (ACE-Step 1.5)' blueprint. The 'village' brief is the same one the YuE2
test used (ComfyUI/user/yue2_tools/bgm_a.json), so the results can be compared directly.
"""
import json
import os
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8188"
# ComfyUI's output folder, for printing result paths: AIAS_COMFY_DIR, else the ComfyUI folder next to this repository.
COMFY_DIR = os.environ.get("AIAS_COMFY_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ComfyUI")
OUT = os.path.normpath(os.path.join(COMFY_DIR, "output"))

BRIEFS = {
    "village": {
        "tags": "instrumental, no vocals, video game background music, cozy fantasy RPG village theme, acoustic guitar, flute, "
                "pizzicato strings, light hand percussion, warm and peaceful, loopable",
        "bpm": 96, "keyscale": "G major",
    },
    "combat": {
        "tags": "instrumental, no vocals, video game background music, dark fantasy survivor combat music, low string pizzicato, "
                "soft metallic percussion, faint bells, warm lantern light against creeping shadows, sparse mid-high range "
                "leaving room for sound effects, steady loopable 8-bar phrases, no abrupt ending",
        "bpm": 100, "keyscale": "D minor",
    },
}
# ACE-Step docs (docs/en/Tutorial.md, INFERENCE.md): lyrics "[Instrumental]" for instrumental tracks,
# vocal language "unknown"; structure tags may describe instrumental sections instead.
LOOP_TAGS = "[Main Theme - low string pizzicato]\n\n[Variation - metallic percussion and faint bells]\n\n[Main Theme - full]"
RUNS = [  # (brief, lyrics, seed)
    ("village", "[Instrumental]", 1001),
    ("village", "", 1001),
    ("combat", "[Instrumental]", 2002),
    ("combat", LOOP_TAGS, 2002),
]
DURATION = 90.0


def post(path, data):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode()[:3000])
        raise


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path).read())


def graph(brief, lyrics, seed, prefix):
    b = BRIEFS[brief]
    return {
        "104": {"class_type": "UNETLoader", "inputs": {"unet_name": "acestep_v1.5_turbo.safetensors", "weight_dtype": "default"}},
        "105": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "qwen_0.6b_ace15.safetensors", "clip_name2": "qwen_4b_ace15.safetensors",
                                                          "type": "ace", "device": "default"}},
        "106": {"class_type": "VAELoader", "inputs": {"vae_name": "ace_1.5_vae.safetensors"}},
        "78": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["104", 0], "shift": 3.0}},
        "94": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {
            "clip": ["105", 0], "tags": b["tags"], "lyrics": lyrics, "seed": seed, "bpm": b["bpm"], "duration": DURATION,
            "timesignature": "4", "language": "unknown", "keyscale": b["keyscale"], "generate_audio_codes": True,
            "cfg_scale": 2.0, "temperature": 0.85, "top_p": 0.9, "top_k": 0, "min_p": 0.0}},
        "47": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["94", 0]}},
        "98": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": DURATION, "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {
            "model": ["78", 0], "positive": ["94", 0], "negative": ["47", 0], "latent_image": ["98", 0],
            "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "18": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["3", 0], "vae": ["106", 0]}},
        "19": {"class_type": "SaveAudio", "inputs": {"audio": ["18", 0], "filename_prefix": prefix}},
    }


def run(g, label):
    t0 = time.time()
    pid = post("/prompt", {"prompt": g})["prompt_id"]
    while True:
        h = get("/history/" + pid)
        if pid in h and h[pid]["status"].get("completed") is not None:
            break
        time.sleep(2)
    h = h[pid]
    print(f"{label}: {h['status']['status_str']} {time.time() - t0:.1f}s", flush=True)
    for m in h["status"]["messages"]:
        if m[0] == "execution_error":
            print("  ERROR:", m[1].get("exception_type"), str(m[1].get("exception_message"))[:1500])
    for out in h.get("outputs", {}).values():
        for a in out.get("audio", []):
            print("  ->", os.path.join(OUT, a["subfolder"], a["filename"]))


only = sys.argv[1:]  # optional: run a subset by index, e.g. "0 2"
for i, (brief, lyrics, seed) in enumerate(RUNS):
    if only and str(i) not in only:
        continue
    tag = {"[Instrumental]": "inst", "": "empty"}.get(lyrics, "sections")
    run(graph(brief, lyrics, seed, f"aiassetstudio_test/ace_{brief}_{tag}"), f"[{i}] {brief} lyrics={lyrics!r} seed={seed}")
