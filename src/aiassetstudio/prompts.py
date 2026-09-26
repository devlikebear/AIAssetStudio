"""Prompt assembly for image assets."""

from .store.models import Project

# Transparent-image format from the Qwen-Image-2.1 model card (verified 2026-09-24, spikes/rgba_test.py).
RGBA_PREFIX = "This is an RGBA image with transparency. "
RGBA_SUFFIX = " The image has alpha channel and the background is transparent."

IMAGE_TEMPLATES = {
    "sprite": "A single game sprite of {description}. Full body, centered, one subject only, no ground, "
    "no cast shadow, no text.",
    # "no frame, no border, no ring": the 2026-09-24 potion icon test came back inside an unrequested glass ring.
    "icon": "A single game item icon of {description}. Centered, the object fills about 80% of the frame, "
    "no frame, no border, no ring, no text.",
}
# With a reference image (sprites only), the sprite is asked for as an edit of picture 1. "Use picture 1 only as a
# style reference" made Qwen copy the reference's subject; this wording drew the new subject in the reference's
# style (user decision 2026-09-25, docs/plans/notes/ref-rgba-validation.md).
REFERENCE_SPRITE_TEMPLATE = (
    "Replace the subject of picture 1 with {description}. Keep the same art style, palette, outline and shading "
    "as picture 1. Full body, centered, one subject only, no ground, no cast shadow, no text."
)
PIXEL_STYLE = "Pixel art, crisp hard-edged pixels, limited palette, no anti-aliasing."


def _clause(text: str) -> str:
    return text.strip().rstrip(".").strip()


def build_image_prompt(project: Project, kind: str, description: str, reference: bool = False) -> str:
    """`reference`: the job passes a reference image as picture 1 (sprites only)."""
    if kind not in IMAGE_TEMPLATES:
        raise ValueError(f"unknown image kind {kind!r}")
    if reference and kind != "sprite":
        raise ValueError("a reference image is only used for sprites")
    template = REFERENCE_SPRITE_TEMPLATE if reference else IMAGE_TEMPLATES[kind]
    body = template.format(description=_clause(description))
    if style := _clause(project.style):
        body += f" Art style: {style}."
    if project.pixel_art:
        body += f" {PIXEL_STYLE}"
    return RGBA_PREFIX + body + RGBA_SUFFIX
