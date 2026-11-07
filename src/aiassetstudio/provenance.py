"""Which model made a file, under what license. Exports warn from this; it is a record, not legal advice."""

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Literal

from .comfy.graphs import (
    ACE_TE_LARGE,
    ACE_TE_SMALL,
    ACE_UNET,
    ACE_VAE,
    LTX_AUDIO_VAE,
    LTX_TE,
    LTX_UNET,
    LTX_UPSCALER,
    LTX_VIDEO_VAE,
    QWEN_BOOK_UNET,
    QWEN_TE,
    QWEN_UNET,
    QWEN_VAE,
    VIGGLE_LORA,
    WAN_LORA_HIGH,
    WAN_LORA_LOW,
    WAN_TE,
    WAN_UNET_HIGH,
    WAN_UNET_LOW,
    WAN_VAE,
    YUE2_CKPT,
)
from .narration import SPEECH_MODEL

LicenseClass = Literal["open", "community", "unknown", "research_only"]
# Worst first. "unknown" outranks "community": nobody has read its terms.
CLASS_ORDER: tuple[LicenseClass, ...] = ("research_only", "unknown", "community", "open")
WARN_CLASSES = ("research_only", "unknown")


@dataclass(frozen=True)
class ModelLicense:
    name: str
    license: str
    class_: LicenseClass


_QWEN = ModelLicense("Qwen-Image-2.1", "Qwen Research License", "research_only")
_ACE = ModelLicense("ACE-Step 1.5", "MIT", "open")
MODEL_LICENSES: dict[str, ModelLicense] = {
    QWEN_UNET: _QWEN,
    QWEN_BOOK_UNET: ModelLicense("Qwen-Image-2.1-Turbo", "Qwen Research License", "research_only"),
    QWEN_TE: _QWEN,
    QWEN_VAE: _QWEN,
    # Its license text was not found on 2026-11-01; an older note calls it non-commercial.
    VIGGLE_LORA: ModelLicense("Viggle Turbo LoRA", "not verified", "unknown"),
    ACE_UNET: _ACE,
    ACE_TE_SMALL: _ACE,
    ACE_TE_LARGE: _ACE,
    ACE_VAE: _ACE,
    YUE2_CKPT: ModelLicense("YuE2", "YuE2 model license", "community"),
    SPEECH_MODEL: ModelLicense("Qwen3-TTS", "Apache License 2.0", "open"),
}
_WAN = ModelLicense("Wan 2.2", "Apache License 2.0", "open")
MODEL_LICENSES |= {f: _WAN for f in (WAN_UNET_HIGH, WAN_UNET_LOW, WAN_LORA_HIGH, WAN_LORA_LOW, WAN_TE, WAN_VAE)}
# No region is excluded; free below USD 10 million of yearly revenue (docs/plans/notes/studio-ltx-2.5.md).
_LTX = ModelLicense("LTX-2.5", "LTX-2.x Community License", "community")
MODEL_LICENSES |= {f: _LTX for f in (LTX_UNET, LTX_TE, LTX_VIDEO_VAE, LTX_AUDIO_VAE, LTX_UPSCALER)}
_UNLISTED = ModelLicense("unlisted model", "not recorded", "unknown")


def _files(models: dict) -> Iterable[str]:
    for value in models.values():
        yield from value if isinstance(value, (list, tuple)) else (value,)


def license_records(models: dict) -> list[dict]:
    """One record per model file of a QWEN_MODELS-style dict, for an asset's meta["licenses"]."""
    records = []
    for file in _files(models):
        entry = MODEL_LICENSES.get(file, _UNLISTED)
        record = asdict(entry) | {"file": file}
        records.append(record | {"class": record.pop("class_")})
    return records


def worst_class(records: Iterable[dict]) -> LicenseClass:
    """The most restricting class among license records; "unknown" for none, since nothing is on record."""
    classes = {r["class"] for r in records}
    return next((c for c in CLASS_ORDER if c in classes), "unknown")


def license_names(records: Iterable[dict]) -> list[str]:
    """Each model once as "name (license)", in order, for a person to read."""
    return list(dict.fromkeys(f"{r['name']} ({r['license']})" for r in records))
