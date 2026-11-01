"""Check that ComfyUI has the nodes and model files each model family needs.

A ComfyUI update can rename nodes, and generation then fails with an opaque validation error.
This names what is missing instead.
"""

from dataclasses import dataclass, field

from .client import ComfyClient, ComfyUnavailable
from .graphs import (
    ACE_TE_LARGE,
    ACE_TE_SMALL,
    ACE_UNET,
    ACE_VAE,
    QWEN_BOOK_UNET,
    QWEN_TE,
    QWEN_UNET,
    QWEN_VAE,
    VIGGLE_LORA,
    YUE2_CKPT,
)


@dataclass(frozen=True)
class Requirement:
    nodes: tuple[str, ...]
    models: dict[str, tuple[str, ...]]  # ComfyUI models/ folder -> files


@dataclass
class FamilyStatus:
    ok: bool
    missing_nodes: list[str] = field(default_factory=list)
    missing_models: list[str] = field(default_factory=list)  # "folder/file"
    reason: str | None = None  # "comfyui_down" when ComfyUI could not be reached


REQUIRED: dict[str, Requirement] = {
    "qwen": Requirement(
        nodes=(
            "UNETLoader",
            "CLIPLoader",
            "VAELoader",
            "TextEncodeQwenImage21",
            "EmptyLatentImage",
            "ViggleTurboLora",
            "BasicGuider",
            "RandomNoise",
            "KSamplerSelect",
            "ViggleTurboSigmas",
            "SamplerCustomAdvanced",
            "VAEDecode",
            "SaveImage",
            "PreviewAny",
            "LoadImage",
            "JoinImageWithAlpha",
            "QwenImage21Cache",
        ),
        models={
            "diffusion_models": (QWEN_UNET,),
            "text_encoders": (QWEN_TE,),
            "vae": (QWEN_VAE,),
            "loras": (VIGGLE_LORA,),
        },
    ),
    "qwen_turbo": Requirement(
        nodes=(
            "UNETLoader",
            "CLIPLoader",
            "VAELoader",
            "TextEncodeQwenImage21",
            "EmptyLatentImage",
            "BasicGuider",
            "RandomNoise",
            "KSamplerSelect",
            "ManualSigmas",
            "SamplerCustomAdvanced",
            "VAEDecode",
            "SaveImage",
            "PreviewAny",
            "LoadImage",
            "JoinImageWithAlpha",
            "QwenImage21Cache",
        ),
        models={
            "diffusion_models": (QWEN_BOOK_UNET,),
            "text_encoders": (QWEN_TE,),
            "vae": (QWEN_VAE,),
        },
    ),
    "ace": Requirement(
        nodes=(
            "UNETLoader",
            "DualCLIPLoader",
            "VAELoader",
            "ModelSamplingAuraFlow",
            "TextEncodeAceStepAudio1.5",
            "ConditioningZeroOut",
            "EmptyAceStep1.5LatentAudio",
            "KSampler",
            "VAEDecodeAudio",
            "SaveAudio",
        ),
        models={
            "diffusion_models": (ACE_UNET,),
            "text_encoders": (ACE_TE_SMALL, ACE_TE_LARGE),
            "vae": (ACE_VAE,),
        },
    ),
    "yue2": Requirement(
        nodes=(
            "CheckpointLoaderSimple",
            "YuE2GenerateABC",
            "YuE2GenerateMusic",
            "ConditioningZeroOut",
            "EmptyYuE2LatentAudio",
            "KSampler",
            "VAEDecodeAudio",
            "SaveAudio",
        ),
        models={"checkpoints": (YUE2_CKPT,)},
    ),
}


async def check(client: ComfyClient) -> dict[str, FamilyStatus]:
    try:
        node_names = set(await client.object_info())
        folders = {folder for req in REQUIRED.values() for folder in req.models}
        available = {folder: set(await client.list_models(folder)) for folder in sorted(folders)}
    except ComfyUnavailable:
        return {family: FamilyStatus(ok=False, reason="comfyui_down") for family in REQUIRED}

    result = {}
    for family, req in REQUIRED.items():
        missing_nodes = [n for n in req.nodes if n not in node_names]
        missing_models = [
            f"{folder}/{name}"
            for folder, names in req.models.items()
            for name in names
            if name not in available[folder]
        ]
        result[family] = FamilyStatus(
            ok=not missing_nodes and not missing_models, missing_nodes=missing_nodes, missing_models=missing_models
        )
    return result
