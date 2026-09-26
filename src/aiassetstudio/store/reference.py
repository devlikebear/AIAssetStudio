"""Project reference images: checked, prepared and copied into the data directory.

The studio never reads the original path again, and never writes to it. Copies are named by content hash and are
not deleted when the project's reference changes, so an asset's meta keeps pointing at the image it was made with.
"""

import hashlib
import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from ..config import Settings
from .files import reference_dir, to_rel

REFERENCE_FORMATS = ("PNG", "JPEG")
MAX_REFERENCE_SIDE = 4096
# TextEncodeQwenImage21 resizes a reference to about 1024x1024 with lanczos, which would blur small pixel art.
# References up to this size are first enlarged by a whole factor with nearest-neighbour (32x32 -> 1024x1024),
# as in the LAST LIGHT validation (docs/plans/notes/ref-rgba-validation.md).
SMALL_REFERENCE_SIDE = 256
REFERENCE_TARGET_SIDE = 1024


class ReferenceImageError(ValueError):
    """The given reference image cannot be used; the message says why."""


def load_reference(path: str | Path) -> Image.Image:
    """Open a PNG or JPEG of at most 4096 px per side as RGBA."""
    path = Path(path)
    if not path.is_file():
        raise ReferenceImageError(f"reference image not found: {path}")
    try:
        with Image.open(path) as img:
            if img.format not in REFERENCE_FORMATS:
                raise ReferenceImageError(f"reference image must be PNG or JPEG, not {img.format}: {path}")
            if max(img.size) > MAX_REFERENCE_SIDE:
                raise ReferenceImageError(
                    f"reference image is {img.width}x{img.height}; the longer side must be at most "
                    f"{MAX_REFERENCE_SIDE} px: {path}"
                )
            return img.convert("RGBA")
    except (UnidentifiedImageError, OSError) as e:
        raise ReferenceImageError(f"could not read reference image {path}: {e}") from e


def prepare_reference(img: Image.Image) -> Image.Image:
    longest = max(img.size)
    factor = REFERENCE_TARGET_SIDE // longest if longest <= SMALL_REFERENCE_SIDE else 1
    if factor < 2:
        return img
    return img.resize((img.width * factor, img.height * factor), Image.Resampling.NEAREST)


def store_reference(settings: Settings, slug: str, img: Image.Image) -> str:
    """Save the prepared copy under the project; returns its path relative to data_dir."""
    buffer = io.BytesIO()
    prepare_reference(img).save(buffer, "PNG")
    data = buffer.getvalue()
    path = reference_dir(settings, slug) / f"{hashlib.sha256(data).hexdigest()[:12]}.png"
    if not path.exists():
        path.write_bytes(data)
    return to_rel(settings, path)
