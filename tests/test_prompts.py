import pytest

from aiassetstudio.prompts import PIXEL_STYLE, RGBA_PREFIX, RGBA_SUFFIX, build_image_prompt
from aiassetstudio.store.models import Project


def project(style: str = "", **spec) -> Project:
    return Project(id=1, slug="demo", name="Demo", style=style, created_at="t", updated_at="t", **spec)


def test_transparency_wrapping():
    prompt = build_image_prompt(project(), "sprite", "a green slime")
    assert prompt.startswith("This is an RGBA image with transparency. ")
    assert prompt.endswith(" The image has alpha channel and the background is transparent.")
    assert prompt.startswith(RGBA_PREFIX) and prompt.endswith(RGBA_SUFFIX)


def test_sprite_text():
    prompt = build_image_prompt(project(), "sprite", "a green slime.")
    assert "A single game sprite of a green slime. Full body, centered, one subject only" in prompt
    assert "no ground, no cast shadow, no text." in prompt
    assert ".." not in prompt


def test_icon_text():
    prompt = build_image_prompt(project(), "icon", "a red health potion")
    assert "A single game item icon of a red health potion. Centered" in prompt
    assert "fills about 80% of the frame" in prompt
    assert "no frame, no border, no ring, no text." in prompt


def test_style_included_or_omitted():
    assert "Art style" not in build_image_prompt(project(), "sprite", "x")
    assert "Art style" not in build_image_prompt(project("   "), "sprite", "x")
    prompt = build_image_prompt(project("dark fantasy, painterly."), "icon", "x")
    assert prompt.endswith("Art style: dark fantasy, painterly." + RGBA_SUFFIX)


def test_unknown_kind():
    with pytest.raises(ValueError):
        build_image_prompt(project(), "tileset", "x")


def test_pixel_art_phrase():
    assert PIXEL_STYLE not in build_image_prompt(project(), "sprite", "x")
    prompt = build_image_prompt(project("dark fantasy", pixel_art=True), "icon", "a key")
    assert prompt.endswith(
        "Art style: dark fantasy. Pixel art, crisp hard-edged pixels, limited palette, no anti-aliasing." + RGBA_SUFFIX
    )


def test_reference_sprite_is_an_edit_of_picture_1():
    prompt = build_image_prompt(project(pixel_art=True), "sprite", "a small slime monster", reference=True)
    assert prompt == (
        RGBA_PREFIX + "Replace the subject of picture 1 with a small slime monster. Keep the same art style, "
        "palette, outline and shading as picture 1. Full body, centered, one subject only, no ground, no cast "
        "shadow, no text. " + PIXEL_STYLE + RGBA_SUFFIX
    )  # the wording checked in docs/plans/notes/ref-rgba-validation.md, section 4
    with pytest.raises(ValueError, match="only used for sprites"):
        build_image_prompt(project(), "icon", "a key", reference=True)
