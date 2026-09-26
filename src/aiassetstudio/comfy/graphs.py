"""ComfyUI API-format graphs. Node names and inputs match ComfyUI 0.37.0 (verified in spikes/rgba_test.py)."""

from dataclasses import dataclass
from typing import Literal

# Qwen-Image-2.1 model files (ComfyUI models/ subfolders in comments).
QWEN_UNET = "qwen_image_2.1_int8_convrot.safetensors"  # diffusion_models
QWEN_TE = "qwen3vl_8b_int8_convrot.safetensors"  # text_encoders
QWEN_VAE = "qwen_image_2.1_vae_bf16.safetensors"  # vae (4-channel RGBA)
VIGGLE_LORA = "Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-lora-r128.safetensors"  # loras

QWEN_MODELS = {"unet": QWEN_UNET, "text_encoder": QWEN_TE, "vae": QWEN_VAE, "lora": VIGGLE_LORA}
QWEN_OUTPUT_NODE = "9"
QWEN_ENCODE_OUTPUT_NODE = "20"
QWEN_TURBO_STEPS = 6
QWEN_TURBO_SIGMAS = "1.0, 0.9375, 0.875, 0.75, 0.5, 0.25"
QWEN_SAMPLER = "euler"

RefMode = Literal["latent", "vision"]


@dataclass(frozen=True)
class Reference:
    """A style reference image already uploaded to ComfyUI's input folder.

    latent: the text encoder sees it and its VAE latents are spliced into the sequence (all four channels).
    vision: only the text encoder's vision tower sees it (alpha composited over white).
    """

    image: str  # LoadImage value, e.g. "aiassetstudio/ref_demo.png"
    mode: RefMode = "latent"


def _vae_node() -> dict:
    return {"class_type": "VAELoader", "inputs": {"vae_name": QWEN_VAE}}


def _qwen_text_nodes(prompt: str, ref: Reference | None = None) -> dict:
    """The text-encoding nodes ("3", "5", and with a reference "15", "16" and in latent mode "4").

    qwen_text_encode() and qwen_t2i_turbo() must build them identically so that ComfyUI reuses the cached
    conditioning of the first in the second.
    """
    encode_inputs = {"clip": ["3", 0], "prompt": prompt, "negative_prompt": "", "resolution": 1024}
    nodes = {
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": QWEN_TE, "type": "qwen_image", "device": "default"}},
        "5": {"class_type": "TextEncodeQwenImage21", "inputs": encode_inputs},
    }
    if ref is not None:
        # LoadImage splits RGBA into RGB and a mask of 1 - alpha; JoinImageWithAlpha turns it back into RGBA.
        nodes["15"] = {"class_type": "LoadImage", "inputs": {"image": ref.image}}
        nodes["16"] = {"class_type": "JoinImageWithAlpha", "inputs": {"image": ["15", 0], "alpha": ["15", 1]}}
        encode_inputs["images.image_1"] = ["16", 0]
        if ref.mode == "latent":
            encode_inputs["vae"] = ["4", 0]
            nodes["4"] = _vae_node()
    return nodes


def qwen_text_encode(prompt: str, ref: Reference | None = None) -> dict:
    """Only the text encoding of `prompt` (and the reference), so ComfyUI caches the conditioning.
    PreviewAny is just the output node a graph needs; it prints a short summary of the tensor."""
    return {
        **_qwen_text_nodes(prompt, ref),
        QWEN_ENCODE_OUTPUT_NODE: {"class_type": "PreviewAny", "inputs": {"source": ["5", 0]}},
    }


def qwen_t2i_turbo(
    prompt: str,
    seed: int,
    prefix: str,
    width: int = 1024,
    height: int = 1024,
    ref: Reference | None = None,
    cache_cpu: bool = False,
) -> dict:
    """Qwen-Image-2.1 text-to-image with the Viggle Turbo 6-step LoRA, optionally with a style reference.
    Output: SaveImage node "9". The latent size comes from EmptyLatentImage, not from the reference: this is a
    style reference, not an edit, so the output need not follow the reference's aspect ratio."""
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": QWEN_UNET, "weight_dtype": "default"}},
        "2": {
            "class_type": "ViggleTurboLora",
            "inputs": {"model": ["1", 0], "lora_name": VIGGLE_LORA, "strength": 1.0},
        },
        "4": _vae_node(),
        **_qwen_text_nodes(prompt, ref),
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["4", 0]}},
        QWEN_OUTPUT_NODE: {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": f"aiassetstudio/{prefix}"},
        },
        "10": {"class_type": "BasicGuider", "inputs": {"model": ["2", 0], "conditioning": ["5", 0]}},
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "12": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": QWEN_SAMPLER}},
        "13": {"class_type": "ViggleTurboSigmas", "inputs": {"latent": ["6", 0], "nodes": QWEN_TURBO_SIGMAS}},
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
    }
    if cache_cpu:
        # Keep the reference KV cache in RAM: one-reference edits peaked at ~15 GB VRAM (2026-09-24).
        graph["17"] = {
            "class_type": "QwenImage21Cache",
            "inputs": {"model": ["2", 0], "device": "cpu", "dtype": "default"},
        }
        graph["10"]["inputs"]["model"] = ["17", 0]
    return graph


def qwen_ref_turbo(
    prompt: str,
    seed: int,
    prefix: str,
    ref_name: str,
    mode: RefMode,
    width: int = 1024,
    height: int = 1024,
    cache_cpu: bool = False,
) -> dict:
    return qwen_t2i_turbo(prompt, seed, prefix, width, height, ref=Reference(ref_name, mode), cache_cpu=cache_cpu)


# --- music ---------------------------------------------------------------------------------------------------------

# ACE-Step 1.5 instrumentals (spikes/acestep_bgm_test.py, 2026-09-24: a 90 s song in 32-36 s).
ACE_UNET = "acestep_v1.5_turbo.safetensors"  # diffusion_models
ACE_TE_SMALL = "qwen_0.6b_ace15.safetensors"  # text_encoders
ACE_TE_LARGE = "qwen_4b_ace15.safetensors"  # text_encoders
ACE_VAE = "ace_1.5_vae.safetensors"  # vae
ACE_MODELS = {"unet": ACE_UNET, "text_encoders": [ACE_TE_SMALL, ACE_TE_LARGE], "vae": ACE_VAE}
ACE_OUTPUT_NODE = "19"
ACE_STEPS = 8
ACE_SAMPLER = "euler"
# The keyscale values TextEncodeAceStepAudio1.5 accepts (a COMBO in ComfyUI 0.37.0).
KEYSCALES = tuple(
    f"{key} {mode}"
    for mode in ("major", "minor")
    for key in ("C", "C#", "Db", "D", "D#", "Eb", "E", "F", "F#", "Gb", "G", "G#", "Ab", "A", "A#", "Bb", "B")
)

# YuE2 songs with vocals, ABC mode (from an earlier yue2_run.py script; a 73 s song took 204 s).
YUE2_CKPT = "yue2_3b_int8_convrot.safetensors"  # checkpoints
YUE2_MODELS = {"checkpoint": YUE2_CKPT}
YUE2_OUTPUT_NODE = "10"
YUE2_STEPS = 32
YUE2_SAMPLER = "dpm_2"


def ace_music(
    tags: str,
    lyrics: str,
    bpm: int,
    seconds: float,
    keyscale: str,
    seed: int,
    prefix: str,
    language: str = "unknown",
) -> dict:
    """ACE-Step 1.5 text to music (the "Text to Audio (ACE-Step 1.5)" blueprint). Output: SaveAudio node "19".
    For instrumentals the ACE-Step docs (docs/en/Tutorial.md) use language "unknown"."""
    return {
        "104": {"class_type": "UNETLoader", "inputs": {"unet_name": ACE_UNET, "weight_dtype": "default"}},
        "105": {
            "class_type": "DualCLIPLoader",
            "inputs": {"clip_name1": ACE_TE_SMALL, "clip_name2": ACE_TE_LARGE, "type": "ace", "device": "default"},
        },
        "106": {"class_type": "VAELoader", "inputs": {"vae_name": ACE_VAE}},
        "78": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["104", 0], "shift": 3.0}},
        "94": {
            "class_type": "TextEncodeAceStepAudio1.5",
            "inputs": {
                "clip": ["105", 0],
                "tags": tags,
                "lyrics": lyrics,
                "seed": seed,
                "bpm": bpm,
                "duration": seconds,
                "timesignature": "4",
                "language": language,
                "keyscale": keyscale,
                "generate_audio_codes": True,
                "cfg_scale": 2.0,
                "temperature": 0.85,
                "top_p": 0.9,
                "top_k": 0,
                "min_p": 0.0,
            },
        },
        "47": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["94", 0]}},
        "98": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": seconds, "batch_size": 1}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["78", 0],
                "positive": ["94", 0],
                "negative": ["47", 0],
                "latent_image": ["98", 0],
                "seed": seed,
                "steps": ACE_STEPS,
                "cfg": 1.0,
                "sampler_name": ACE_SAMPLER,
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "18": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["3", 0], "vae": ["106", 0]}},
        ACE_OUTPUT_NODE: {
            "class_type": "SaveAudio",
            "inputs": {"audio": ["18", 0], "filename_prefix": f"aiassetstudio/{prefix}"},
        },
    }


def yue2_song(style: str, lyrics: str, seed: int, max_duration: float, prefix: str) -> dict:
    """YuE2 song with vocals: the ABC score first, then music from it (the "Text to Music (YuE2)" blueprint).
    The song length comes from YuE2GenerateMusic (output 1), up to `max_duration`. Output: SaveAudio node "10"."""
    return {
        "15": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": YUE2_CKPT}},
        "24": {
            "class_type": "YuE2GenerateABC",
            "inputs": {
                "clip": ["15", 1],
                "style": style,
                "lyrics": lyrics,
                "seed": seed,
                "mode": "full",
                "max_abc_tokens": 8192,
                "temperature": 0.7,
                "top_p": 0.9,
                "top_k": 30,
                "repetition_penalty": 1.005,
                "penalty_window": 100,
            },
        },
        "25": {
            "class_type": "YuE2GenerateMusic",
            "inputs": {
                "clip": ["15", 1],
                "style": style,
                "lyrics": lyrics,
                "abc": ["24", 0],
                "seed": seed,
                "mode": "full",
                "max_duration": max_duration,
                "temperature": 1.0,
                "top_p": 0.95,
                "top_k": 100,
                "repetition_penalty": 1.2,
            },
        },
        "18": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["25", 0]}},
        "5": {"class_type": "EmptyYuE2LatentAudio", "inputs": {"seconds": ["25", 1], "batch_size": 1}},
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["15", 0],
                "seed": seed,
                "steps": YUE2_STEPS,
                "cfg": 1.0,
                "sampler_name": YUE2_SAMPLER,
                "scheduler": "sgm_uniform",
                "positive": ["25", 0],
                "negative": ["18", 0],
                "latent_image": ["5", 0],
                "denoise": 1.0,
            },
        },
        "9": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["8", 0], "vae": ["15", 2]}},
        YUE2_OUTPUT_NODE: {
            "class_type": "SaveAudio",
            "inputs": {"audio": ["9", 0], "filename_prefix": f"aiassetstudio/{prefix}"},
        },
    }
