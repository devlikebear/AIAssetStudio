"""Can the official Qwen-Image-2.1-Turbo replace the Viggle LoRA and its custom node? T1.A.3.

usage: official_turbo.py <prompt.txt> <out dir> <reference image>...; run with ComfyUI up. No custom node is used.
The prompt stays outside the repository: it holds a work's text. Viggle's pictures for the same prompt and seeds come
from three_refs.py.
"""

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from aiassetstudio.comfy.client import ComfyClient  # noqa: E402
from aiassetstudio.comfy.graphs import QWEN_VAE, Reference, _qwen_text_nodes, qwen_text_encode  # noqa: E402

UNET = "qwen_image_2.1_turbo_int8_convrot.safetensors"
W, H = 1184, 880
SEEDS = (8101, 8102, 8103)
# Published with the checkpoint's schedule; the model card says it is saved in the checkpoint.
SIGMAS = "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0.0"
VARIANTS = {
    "manual_euler": ("euler", {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS}}),
    "linquad_ersde": (
        "er_sde",
        {
            "class_type": "BasicScheduler",
            "inputs": {"model": ["1", 0], "scheduler": "linear_quadratic", "steps": 8, "denoise": 1.0},
        },
    ),
}


def graph(prompt: str, seed: int, prefix: str, refs: list[Reference], sampler: str, sigmas: dict) -> dict:
    nodes = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": QWEN_VAE}},
        **_qwen_text_nodes(prompt, refs),
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["4", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
        "10": {"class_type": "BasicGuider", "inputs": {"model": ["17", 0], "conditioning": ["5", 0]}},
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "12": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": sampler}},
        "13": sigmas,
        "14": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["11", 0],
                "guider": ["10", 0],
                "sampler": ["12", 0],
                "sigmas": ["13", 0],
                "latent_image": ["6", 0],
            },
        },
        "17": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "cpu", "dtype": "default"}},
    }
    return nodes


async def main() -> None:
    prompt = Path(sys.argv[1]).read_text(encoding="utf-8-sig").strip()
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    client = ComfyClient("http://127.0.0.1:8188")
    try:
        names = [
            await client.upload_image(Path(p), f"threeref_{i}.png", "studio_spike") for i, p in enumerate(sys.argv[3:])
        ]
        refs = [Reference(name, "latent") for name in names]
        t0 = time.monotonic()
        encode_id = str(uuid.uuid4())
        await client.submit(qwen_text_encode(prompt, refs), prompt_id=encode_id)
        await client.free(unload_models=True, free_memory=False)
        await client.wait(encode_id, timeout=600)
        print(json.dumps({"encode_s": round(time.monotonic() - t0, 1)}), flush=True)
        for variant, (sampler, sigmas) in VARIANTS.items():
            for seed in SEEDS[: 3 if variant == "manual_euler" else 1]:
                t1 = time.monotonic()
                gen_id = str(uuid.uuid4())
                await client.submit(
                    graph(prompt, seed, f"studio_spike/turbo_{variant}_{seed}", refs, sampler, sigmas), prompt_id=gen_id
                )
                entry = await client.wait(gen_id, timeout=600)
                draw = time.monotonic() - t1
                stats = await client.system_stats()
                file = entry["outputs"]["9"]["images"][0]
                (out / f"{variant}_{seed}.png").write_bytes(
                    await client.fetch_output(file["filename"], file["subfolder"])
                )
                print(
                    json.dumps(
                        {
                            "variant": variant,
                            "seed": seed,
                            "draw_s": round(draw, 1),
                            "vram_free_gb": round(stats["devices"][0]["vram_free"] / 2**30, 2),
                            "ram_free_gb": round(stats["system"]["ram_free"] / 2**30, 2),
                        }
                    ),
                    flush=True,
                )
    finally:
        await client.aclose()


asyncio.run(main())
