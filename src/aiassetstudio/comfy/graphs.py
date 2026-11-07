"""ComfyUI API-format graphs. Node names and inputs match ComfyUI 0.37.0 (verified in spikes/rgba_test.py)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

# Qwen-Image-2.1 model files (ComfyUI models/ subfolders in comments). The UNET, the LoRA and the graphs built on them
# are how images were made before the official Turbo; only spikes and the records of old assets use them now.
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

# The official Qwen-Image-2.1-Turbo, for every image: no LoRA or custom node (spikes/studio/official_turbo.py, 2026-11-01:
# 13 s a 1184x880 picture with three references, against Viggle's 20 s, same faces and places). The schedule is the
# one saved in the checkpoint; ComfyUI 0.37.0 does not read it from there. CFG is 1: BasicGuider has no negative prompt.
# Sprites and icons moved to it after spikes/studio/sprite_turbo.py (2026-11-02): same transparency, pixel grid and
# reference style, 25-30% faster.
QWEN_BOOK_UNET = "qwen_image_2.1_turbo_int8_convrot.safetensors"  # diffusion_models
QWEN_BOOK_MODELS = {"unet": QWEN_BOOK_UNET, "text_encoder": QWEN_TE, "vae": QWEN_VAE}
QWEN_BOOK_STEPS = 8
QWEN_BOOK_SIGMAS = "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0.0"

# Wan 2.2 14B image to video with the 4-step Lightning LoRAs (spikes/studio/render_video.py, 2026-11-01): 832x624, 81
# frames at 16 fps, about 190 s a clip, free RAM down to 1.8 GB. CFG is 1, so a negative prompt has no effect: limits on
# the motion must be in the prompt itself.
WAN_UNET_HIGH = "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"  # diffusion_models
WAN_UNET_LOW = "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"  # diffusion_models
WAN_LORA_HIGH = "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"  # loras
WAN_LORA_LOW = "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"  # loras
WAN_TE = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"  # text_encoders
WAN_VAE = "wan_2.1_vae.safetensors"  # vae
WAN_MODELS = {
    "unet": (WAN_UNET_HIGH, WAN_UNET_LOW),
    "lora": (WAN_LORA_HIGH, WAN_LORA_LOW),
    "text_encoder": WAN_TE,
    "vae": WAN_VAE,
}
WAN_OUTPUT_NODE = "17"
WAN_STEPS = 4
WAN_SWITCH_STEP = 2  # the high-noise model takes the first steps, the low-noise model the rest
WAN_SHIFT = 5.0
WAN_WIDTH, WAN_HEIGHT, WAN_FRAMES, WAN_FPS = 832, 624, 81, 16

# LTX-2.5, distilled 22B, after ComfyUI's template video_ltx2_5_i2v.json: 8 steps at half size, a x2 latent upscale,
# 3 more steps; no prompt enhancer (docs/plans/notes/studio-ltx-2.5.md, 2026-11-03: 1024x768, 5 s at 24 fps in about
# 85 s, and no strangers walking into empty space as with Wan). It makes sound too; an empty audio latent goes in and
# the sound is dropped. The repository is gated: a person agrees to its license on Hugging Face.
LTX_UNET = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"  # diffusion_models
LTX_TE = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"  # text_encoders
LTX_VIDEO_VAE = "ltx-2.5-video-vae-bf16.safetensors"  # vae
LTX_AUDIO_VAE = "ltx-2.5-audio-vae-bf16.safetensors"  # vae
LTX_UPSCALER = "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"  # latent_upscale_models
LTX_MODELS = {
    "unet": LTX_UNET,
    "text_encoder": LTX_TE,
    "vae": (LTX_VIDEO_VAE, LTX_AUDIO_VAE),
    "upscaler": LTX_UPSCALER,
}
LTX_OUTPUT_NODE = "30"
LTX_STEPS = 8 + 3
LTX_WIDTH, LTX_HEIGHT, LTX_FPS = 1024, 768, 24
LTX_SIGMAS_LOW = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
LTX_SIGMAS_HIGH = "0.85, 0.7250, 0.4219, 0.0"
LTX_NEGATIVE = "pc game, console game, video game, cartoon, childish, ugly"
# The template's own opening for an image to video prompt.
LTX_PROMPT_PREFIX = "Use the provided start image as the first frame."

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


def _as_refs(ref: Reference | Sequence[Reference] | None) -> tuple[Reference, ...]:
    if ref is None:
        return ()
    return (ref,) if isinstance(ref, Reference) else tuple(ref)


def _qwen_text_nodes(prompt: str, ref: Reference | Sequence[Reference] | None = None) -> dict:
    """The text-encoding nodes ("3", "5", and with a reference "15", "16" and in latent mode "4"; more references
    add "32", "42", "33", "43"...).

    qwen_text_encode() and qwen_t2i_turbo() must build them identically so that ComfyUI reuses the cached
    conditioning of the first in the second.
    """
    encode_inputs = {"clip": ["3", 0], "prompt": prompt, "negative_prompt": "", "resolution": 1024}
    nodes = {
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": QWEN_TE, "type": "qwen_image", "device": "default"}},
        "5": {"class_type": "TextEncodeQwenImage21", "inputs": encode_inputs},
    }
    for i, reference in enumerate(_as_refs(ref), 1):
        load, join = ("15", "16") if i == 1 else (f"3{i}", f"4{i}")
        # LoadImage splits RGBA into RGB and a mask of 1 - alpha; JoinImageWithAlpha turns it back into RGBA.
        nodes[load] = {"class_type": "LoadImage", "inputs": {"image": reference.image}}
        nodes[join] = {"class_type": "JoinImageWithAlpha", "inputs": {"image": [load, 0], "alpha": [load, 1]}}
        encode_inputs[f"images.image_{i}"] = [join, 0]
        if reference.mode == "latent":
            encode_inputs["vae"] = ["4", 0]
            nodes["4"] = _vae_node()
    return nodes


def qwen_text_encode(prompt: str, ref: Reference | Sequence[Reference] | None = None) -> dict:
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
    ref: Reference | Sequence[Reference] | None = None,
    cache_cpu: bool = False,
) -> dict:
    """Qwen-Image-2.1 text-to-image with the Viggle Turbo 6-step LoRA, optionally with references.
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


def qwen_book_page(
    prompt: str,
    seed: int,
    prefix: str,
    width: int,
    height: int,
    refs: Sequence[Reference] = (),
) -> dict:
    """A picture, sprite or icon with the official Turbo checkpoint. Output: SaveImage node "9". With references the KV cache
    stays in RAM, as in qwen_t2i_turbo."""
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": QWEN_BOOK_UNET, "weight_dtype": "default"}},
        "4": _vae_node(),
        **_qwen_text_nodes(prompt, refs),
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["4", 0]}},
        QWEN_OUTPUT_NODE: {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": f"aiassetstudio/{prefix}"},
        },
        "10": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["5", 0]}},
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "12": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": QWEN_SAMPLER}},
        "13": {"class_type": "ManualSigmas", "inputs": {"sigmas": QWEN_BOOK_SIGMAS}},
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
    if refs:
        graph["17"] = {
            "class_type": "QwenImage21Cache",
            "inputs": {"model": ["1", 0], "device": "cpu", "dtype": "default"},
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


def _wan_text_nodes(prompt: str) -> dict:
    """The nodes wan_text_encode() and wan_i2v_lightning() share, built identically so ComfyUI reuses the conditioning."""

    def encode(text: str) -> dict:
        return {"class_type": "CLIPTextEncode", "inputs": {"clip": ["7", 0], "text": text}}

    loader = {"clip_name": WAN_TE, "type": "wan", "device": "default"}
    return {"7": {"class_type": "CLIPLoader", "inputs": loader}, "8": encode(prompt), "9": encode("")}


def wan_text_encode(prompt: str) -> dict:
    """Only the text encoding, so it can leave memory before the two video models load. In one prompt the encoder's
    6.7 GB stayed in RAM beside them: free commit on a 32 GB PC with its default page file reached 0.1 GB, and a clip
    failed with Windows error 1450 reading its model (2026-11-01). PreviewAny nodes make both results outputs."""
    previews = {
        node: {"class_type": "PreviewAny", "inputs": {"source": [source, 0]}}
        for node, source in (("20", "8"), ("21", "9"))
    }
    return _wan_text_nodes(prompt) | previews


def wan_i2v_lightning(
    prompt: str,
    image: str,
    seed: int,
    prefix: str,
    width: int = WAN_WIDTH,
    height: int = WAN_HEIGHT,
    frames: int = WAN_FRAMES,
) -> dict:
    """A clip that starts from `image` (a LoadImage value). The negative prompt must be wired but is ignored at CFG 1."""

    def node(class_type: str, **inputs) -> dict:
        return {"class_type": class_type, "inputs": inputs}

    sampler = {"steps": WAN_STEPS, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "noise_seed": seed}
    condition = {"positive": ["12", 0], "negative": ["12", 1]}
    return {
        "1": node("UNETLoader", unet_name=WAN_UNET_HIGH, weight_dtype="default"),
        "2": node("UNETLoader", unet_name=WAN_UNET_LOW, weight_dtype="default"),
        "3": node("LoraLoaderModelOnly", model=["1", 0], lora_name=WAN_LORA_HIGH, strength_model=1.0),
        "4": node("LoraLoaderModelOnly", model=["2", 0], lora_name=WAN_LORA_LOW, strength_model=1.0),
        "5": node("ModelSamplingSD3", model=["3", 0], shift=WAN_SHIFT),
        "6": node("ModelSamplingSD3", model=["4", 0], shift=WAN_SHIFT),
        **_wan_text_nodes(prompt),
        "10": node("VAELoader", vae_name=WAN_VAE),
        "11": node("LoadImage", image=image),
        "12": node(
            "WanImageToVideo",
            positive=["8", 0],
            negative=["9", 0],
            vae=["10", 0],
            start_image=["11", 0],
            width=width,
            height=height,
            length=frames,
            batch_size=1,
        ),
        "13": node(
            "KSamplerAdvanced",
            model=["5", 0],
            add_noise="enable",
            latent_image=["12", 2],
            start_at_step=0,
            end_at_step=WAN_SWITCH_STEP,
            return_with_leftover_noise="enable",
            **sampler,
            **condition,
        ),
        "14": node(
            "KSamplerAdvanced",
            model=["6", 0],
            add_noise="disable",
            latent_image=["13", 0],
            start_at_step=WAN_SWITCH_STEP,
            end_at_step=10000,
            return_with_leftover_noise="disable",
            **sampler,
            **condition,
        ),
        "15": node("VAEDecode", samples=["14", 0], vae=["10", 0]),
        "16": node("CreateVideo", images=["15", 0], fps=float(WAN_FPS)),
        WAN_OUTPUT_NODE: node("SaveVideo", video=["16", 0], filename_prefix=prefix, format="mp4"),
    }


def ltx_frames(seconds: float) -> int:
    return round(seconds * LTX_FPS) + 1


def _ltx_text_nodes(prompt: str) -> dict:
    """The nodes ltx_text_encode() and ltx_i2v() share, built identically so ComfyUI reuses the conditioning."""

    def encode(text: str) -> dict:
        return {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": text}}

    loader = {"clip_name": LTX_TE, "type": "ltxv", "device": "default"}
    return {"2": {"class_type": "CLIPLoader", "inputs": loader}, "3": encode(prompt), "4": encode(LTX_NEGATIVE)}


def ltx_text_encode(prompt: str) -> dict:
    """Only the text encoding, so its 14 GB encoder can leave memory before the 20 GB video model loads."""
    previews = {
        node: {"class_type": "PreviewAny", "inputs": {"source": [source, 0]}}
        for node, source in (("40", "3"), ("41", "4"))
    }
    return _ltx_text_nodes(prompt) | previews


def ltx_i2v(prompt: str, image: str, seed: int, prefix: str, seconds: float = 5) -> dict:
    """A clip that starts from `image` (a LoadImage value), LTX_WIDTH x LTX_HEIGHT."""

    def node(class_type: str, **inputs) -> dict:
        return {"class_type": class_type, "inputs": inputs}

    frames = ltx_frames(seconds)
    vae, picture = ["6", 0], ["9", 0]
    return _ltx_text_nodes(prompt) | {
        "1": node("UNETLoader", unet_name=LTX_UNET, weight_dtype="default"),
        "5": node("LTXVConditioning", positive=["3", 0], negative=["4", 0], frame_rate=float(LTX_FPS)),
        "6": node("VAELoader", vae_name=LTX_VIDEO_VAE),
        "7": node("VAELoader", vae_name=LTX_AUDIO_VAE),
        "8": node("LoadImage", image=image),
        "9": node("LTXVPreprocess", image=["8", 0], img_compression=18),
        "10": node("EmptyLTXVLatentVideo", width=LTX_WIDTH // 2, height=LTX_HEIGHT // 2, length=frames, batch_size=1),
        "11": node("LTXVImgToVideoInplace", vae=vae, image=picture, latent=["10", 0], strength=0.7, bypass=False),
        "12": node("LTXVEmptyLatentAudio", frames_number=frames, frame_rate=LTX_FPS, batch_size=1, audio_vae=["7", 0]),
        "13": node("LTXVConcatAVLatent", video_latent=["11", 0], audio_latent=["12", 0]),
        "14": node(
            "LTXVDualCFGGuider", model=["1", 0], positive=["5", 0], negative=["5", 1], video_cfg=1.0, audio_cfg=1.0
        ),
        "15": node("RandomNoise", noise_seed=seed),
        "16": node("KSamplerSelect", sampler_name="euler_ancestral"),
        "17": node("ManualSigmas", sigmas=LTX_SIGMAS_LOW),
        "18": node(
            "SamplerCustomAdvanced",
            noise=["15", 0],
            guider=["14", 0],
            sampler=["16", 0],
            sigmas=["17", 0],
            latent_image=["13", 0],
        ),
        "19": node("LTXVSeparateAVLatent", av_latent=["18", 0]),
        "20": node("LatentUpscaleModelLoader", model_name=LTX_UPSCALER),
        "21": node("LTXVLatentUpsampler", samples=["19", 0], upscale_model=["20", 0], vae=vae),
        "22": node("LTXVImgToVideoInplace", vae=vae, image=picture, latent=["21", 0], strength=1.0, bypass=False),
        "23": node("LTXVConcatAVLatent", video_latent=["22", 0], audio_latent=["19", 1]),
        "24": node("RandomNoise", noise_seed=seed + 1),
        "25": node("ManualSigmas", sigmas=LTX_SIGMAS_HIGH),
        "26": node(
            "SamplerCustomAdvanced",
            noise=["24", 0],
            guider=["14", 0],
            sampler=["16", 0],
            sigmas=["25", 0],
            latent_image=["23", 0],
        ),
        "27": node("LTXVSeparateAVLatent", av_latent=["26", 0]),
        "28": node(
            "VAEDecodeTiled",
            samples=["27", 0],
            vae=vae,
            tile_size=512,
            overlap=64,
            temporal_size=64,
            temporal_overlap=16,
        ),
        "29": node("CreateVideo", images=["28", 0], fps=float(LTX_FPS)),
        LTX_OUTPUT_NODE: node("SaveVideo", video=["29", 0], filename_prefix=prefix, format="mp4"),
    }
