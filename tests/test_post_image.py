import numpy as np
import pytest
from PIL import Image, ImageFilter

from aiassetstudio.post.image import (
    TRIM_PAD,
    PixelSpec,
    alpha_stats,
    clean_alpha,
    colors_used,
    drop_detached_faint,
    hex_to_rgb,
    make_preview,
    pixelate,
    process_image,
    reference_ground,
    square_canvas,
    trim_to_content,
    upscale_nearest,
)


def generated(size=(512, 512), box=(160, 128, 352, 384), glass=(200, 300, 312, 360)) -> Image.Image:
    """Like a Qwen RGBA output: background alpha 1..8, an opaque subject, a translucent (alpha 100) glass part."""
    w, h = size
    rng = np.random.default_rng(1)
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., :3] = (90, 120, 150)
    rgba[..., 3] = rng.integers(1, 9, (h, w))
    left, top, right, bottom = box
    rgba[top:bottom, left:right] = (200, 40, 40, 255)
    if glass:
        gl, gt, gr, gb = glass
        rgba[gt:gb, gl:gr] = (180, 220, 255, 100)
    return Image.fromarray(rgba, "RGBA")


def arr(img: Image.Image) -> np.ndarray:
    return np.asarray(img)


def test_clean_alpha_zeroes_residual_background():
    raw = generated()
    assert alpha_stats(raw)["border_mean"] > 0
    out = arr(clean_alpha(raw))
    assert out[:100, :100].max() == 0  # background: alpha and RGB zeroed
    assert tuple(out[200, 200]) == (200, 40, 40, 255)  # subject untouched
    assert tuple(out[330, 250]) == (180, 220, 255, 100)  # translucent glass kept
    stats = alpha_stats(Image.fromarray(out, "RGBA"))
    assert stats["border_mean"] == 0 and stats["border_max"] == 0
    assert stats["partial"] > 0


def test_clean_alpha_converts_rgb():
    out = clean_alpha(Image.new("RGB", (8, 8), (1, 2, 3)))
    assert out.mode == "RGBA"
    assert arr(out)[..., 3].min() == 255


def test_alpha_stats_fractions():
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    img.paste((255, 0, 0, 255), (0, 0, 100, 25))
    img.paste((255, 0, 0, 128), (0, 25, 100, 50))
    stats = alpha_stats(img)
    assert (stats["transparent"], stats["opaque"], stats["partial"]) == (0.5, 0.25, 0.25)
    assert stats["border_max"] == 255


def test_sprite_trimmed_with_clean_border():
    out = process_image(generated(), "sprite")
    # subject box (160,128)-(352,384) plus TRIM_PAD on every side
    assert out.size == (352 - 160 + 2 * TRIM_PAD, 384 - 128 + 2 * TRIM_PAD)
    stats = alpha_stats(out)
    assert stats["border_mean"] == 0 and stats["border_max"] == 0
    assert stats["opaque"] > 0.3 and stats["partial"] > 0


def test_trim_never_enlarges_canvas():
    touching = generated(box=(0, 100, 200, 300), glass=None)
    out = trim_to_content(clean_alpha(touching))
    assert out.size == (200 + TRIM_PAD, 200 + 2 * TRIM_PAD)
    assert alpha_stats(out)["border_max"] == 255  # the subject still touches the left edge


def with_pixels(img: Image.Image, *patches) -> Image.Image:
    """Copy of `img` with (left, top, right, bottom, alpha) patches of grey pixels."""
    rgba = np.array(img)
    for left, top, right, bottom, alpha in patches:
        rgba[top:bottom, left:right] = (120, 120, 120, alpha)
    return Image.fromarray(rgba, "RGBA")


def test_detached_faint_specks_dropped():
    # 2026-09-25 smoke failure: a translucent backdrop band (alpha 8..15) with specks of alpha 16..21 at both
    # frame edges; the specks survived clean_alpha and widened the trim to the full frame width.
    raw = with_pixels(
        generated(box=(0, 0, 0, 0), glass=None),
        (0, 200, 512, 400, 12),
        (0, 250, 2, 262, 21),
        (510, 300, 512, 305, 18),
        (160, 128, 352, 384, 255),  # the subject, drawn over the band
    )
    out = process_image(raw, "sprite")
    assert out.size == (352 - 160 + 2 * TRIM_PAD, 384 - 128 + 2 * TRIM_PAD)
    assert alpha_stats(out)["border_max"] == 0


def test_attached_faint_glow_kept():
    glow = with_pixels(generated(glass=None), (140, 108, 372, 404, 30), (160, 128, 352, 384, 255))
    cleaned = np.asarray(drop_detached_faint(clean_alpha(glow)))
    assert cleaned[110, 150, 3] == 30  # the faint halo touches the opaque subject, so it stays


def test_detached_solid_part_and_tiny_speck():
    raw = with_pixels(generated(glass=None), (400, 450, 420, 470, 255), (40, 40, 43, 43, 255))
    cleaned = np.asarray(drop_detached_faint(clean_alpha(raw)))
    assert cleaned[460, 410, 3] == 255  # a separate opaque part (400 px) is kept
    assert cleaned[41, 41, 3] == 0  # 9 opaque pixels on their own are noise


def test_all_translucent_subject_kept():
    ghost = with_pixels(generated(box=(0, 0, 0, 0), glass=None), (200, 200, 300, 300, 100), (0, 10, 2, 20, 18))
    cleaned = np.asarray(drop_detached_faint(clean_alpha(ghost)))
    assert cleaned[250, 250, 3] == 100  # core threshold drops to half the max alpha
    assert cleaned[15, 1, 3] == 0


def test_icon_is_square_and_centered():
    # 300 px wide content: 6% would be 18 px, so the 32 px minimum applies, once (no extra trim padding).
    out = process_image(generated(box=(100, 200, 400, 300), glass=None), "icon")
    w, h = out.size
    assert w == h == 300 + 2 * TRIM_PAD
    a = arr(out)[..., 3]
    ys, xs = np.nonzero(a)
    assert abs((xs.min() + xs.max()) / 2 - w / 2) <= 1
    assert abs((ys.min() + ys.max()) / 2 - h / 2) <= 1
    assert alpha_stats(out)["border_max"] == 0


def test_large_icon_margin_is_six_percent():
    # like the 2026-09-25 sword: 792 px tall content -> 48 px margin (6%), 888 px canvas (it was 959)
    out = process_image(generated(size=(1024, 1024), box=(372, 116, 651, 908), glass=None), "icon")
    assert out.size == (792 + 2 * 48, 792 + 2 * 48)


def test_empty_image():
    empty = Image.fromarray(np.full((64, 64, 4), 5, np.uint8), "RGBA")  # only residual alpha
    for kind in ("sprite", "icon"):
        out = process_image(empty, kind)
        assert arr(out)[..., 3].max() == 0
        assert make_preview(out).size[0] <= 256


def test_preview_size():
    assert make_preview(Image.new("RGBA", (1024, 600))).size == (256, 150)
    assert make_preview(Image.new("RGBA", (300, 900))).size == (85, 256)
    assert make_preview(Image.new("RGBA", (200, 100))).size == (200, 100)


def test_square_canvas_margin():
    out = square_canvas(Image.new("RGBA", (100, 50), (255, 0, 0, 255)), pad_ratio=0.1)
    assert out.size == (120, 120)
    assert arr(out)[60, 60, 3] == 255 and arr(out)[0, 0, 3] == 0


def test_unknown_kind():
    with pytest.raises(ValueError):
        process_image(generated(), "tileset")


# --- pixel art ------------------------------------------------------------------------------------

SPRITE_COLORS = np.array(
    [(24, 20, 37), (190, 60, 50), (240, 200, 80), (60, 140, 70), (80, 100, 200), (230, 230, 220)], np.uint8
)


def pixel_sprite() -> np.ndarray:
    """16x16 sprite with 6 colors. The subject spans x 2..13 and y 1..14: it touches the 1-cell margin at the top
    and bottom and is centered, which is where pixelate() puts a 12x14 subject."""
    rng = np.random.default_rng(7)
    sprite = np.zeros((16, 16, 4), np.uint8)
    sprite[1:15, 2:14, :3] = SPRITE_COLORS[rng.integers(0, len(SPRITE_COLORS), (14, 12))]
    sprite[1:15, 2:14, 3] = 255
    for y, x in ((1, 2), (1, 13), (14, 2), (14, 13), (7, 2), (8, 13)):  # notches: not a plain rectangle
        sprite[y, x] = 0
    return sprite


def as_generated(sprite: np.ndarray, factor: int = 40, seed: int = 3) -> Image.Image:
    """What Qwen makes of pixel art: enlarged, edges blurred, colors jittered, background alpha 2..6."""
    big = Image.fromarray(sprite, "RGBA").resize((16 * factor, 16 * factor), Image.Resampling.NEAREST)
    big = np.array(big.filter(ImageFilter.GaussianBlur(3))).astype(np.int16)
    rng = np.random.default_rng(seed)
    big[..., :3] += rng.integers(-6, 7, big[..., :3].shape).astype(np.int16)
    background = big[..., 3] == 0
    big[..., 3][background] = rng.integers(2, 7, np.count_nonzero(background))
    return Image.fromarray(np.clip(big, 0, 255).astype(np.uint8), "RGBA")


def nearest_sprite_color(rgb: np.ndarray) -> np.ndarray:
    return np.abs(rgb[:, None, :].astype(int) - SPRITE_COLORS[None, :, :].astype(int)).sum(axis=2).argmin(axis=1)


def test_pixelate_round_trip():
    sprite = pixel_sprite()
    out = arr(pixelate(as_generated(sprite), 16, 16, 6))
    assert out.shape == (16, 16, 4)
    assert set(np.unique(out[..., 3])) <= {0, 255}
    assert colors_used(Image.fromarray(out, "RGBA")) <= 6
    same_alpha = out[..., 3] == sprite[..., 3]
    both = (out[..., 3] == 255) & (sprite[..., 3] == 255)
    # an opaque pixel matches if it is closest to the right original color and within a few levels of it
    right = np.zeros((16, 16), bool)
    right[both] = nearest_sprite_color(out[both][:, :3]) == nearest_sprite_color(sprite[both][:, :3])
    right[both] &= np.abs(out[both][:, :3].astype(int) - sprite[both][:, :3].astype(int)).max(axis=1) <= 12
    same = same_alpha & (right | (sprite[..., 3] == 0))
    assert same.mean() >= 0.95, same.mean()


def test_pixelate_fixed_palette():
    palette = [hex_to_rgb(c) for c in ("#1a1c2c", "#b13e53", "#ffcd75", "#38b764", "#41a6f6")]
    out = arr(pixelate(as_generated(pixel_sprite()), 16, 16, 4, palette=palette))
    opaque = out[..., 3] == 255
    used = {tuple(int(v) for v in c) for c in out[opaque][:, :3]}
    assert used <= set(palette)
    assert len(used) <= 4


def test_pixelate_keeps_aspect_ratio():
    wide = np.zeros((300, 600, 4), np.uint8)
    wide[100:200, 100:500] = (200, 40, 40, 255)  # 400 x 100 subject
    report = {}
    out = arr(pixelate(Image.fromarray(wide, "RGBA"), 16, 16, 4, report=report))
    assert report == {"fit": "stretch", "reason": "no grid"}  # a plain shape: two edges per axis are not a grid
    ys, xs = np.nonzero(out[..., 3])
    assert (xs.max() - xs.min() + 1, ys.max() - ys.min() + 1) == (14, 4)  # 14 wide, 400/100 -> 3.5 rounds to 4
    assert (xs.min(), ys.min()) == (1, 6)  # centered


def test_pixelate_bottom_anchor():
    wide = np.zeros((300, 600, 4), np.uint8)
    wide[100:200, 100:500] = (200, 40, 40, 255)
    out = arr(pixelate(Image.fromarray(wide, "RGBA"), 16, 16, 4, anchor="bottom"))
    ys, _ = np.nonzero(out[..., 3])
    assert ys.max() == 14  # feet on the row above the 1-cell margin


def test_pixelate_keeps_small_distinct_color():
    # A body in many close shades plus two small yellow eyes; 3 colors allowed: the eyes must stay yellow.
    body = np.zeros((320, 320, 4), np.uint8)
    for i, y in enumerate(range(0, 320, 40)):
        body[y : y + 40, :] = (30 + 6 * i, 30 + 4 * i, 60 + 5 * i, 255)
    body[80:120, 80:120] = (250, 220, 60, 255)
    body[80:120, 200:240] = (250, 220, 60, 255)
    out = arr(pixelate(Image.fromarray(body, "RGBA"), 10, 10, 3))
    assert tuple(out[3, 3, :3]) == (250, 220, 60)
    assert colors_used(Image.fromarray(out, "RGBA")) <= 3


def test_pixelate_empty_image():
    out = pixelate(Image.fromarray(np.full((64, 64, 4), 5, np.uint8), "RGBA"), 32, 32, 8)
    assert out.size == (32, 32)
    assert arr(out)[..., 3].max() == 0


def drawn_in_blocks(sprite: np.ndarray, widths, heights, seed: int = 3) -> Image.Image:
    """Pixel art as Qwen draws it: each pixel a block of the given column width and row height, edges blurred,
    colors jittered."""
    big = np.repeat(np.repeat(sprite, heights, axis=0), widths, axis=1)
    big = np.array(Image.fromarray(big, "RGBA").filter(ImageFilter.GaussianBlur(3))).astype(np.int16)
    big[..., :3] += np.random.default_rng(seed).integers(-6, 7, big[..., :3].shape).astype(np.int16)
    return Image.fromarray(np.clip(big, 0, 255).astype(np.uint8), "RGBA")


def test_pixelate_rebuilds_the_model_grid():
    # Blocks of 40 px: the subject comes back one pixel per block, exactly, at 1x (12 x 14 blocks, 14 x 14 room).
    sprite = pixel_sprite()
    report = {}
    out = arr(pixelate(as_generated(sprite), 16, 16, 6, report=report))
    assert report == {"fit": "native", "scale": 1, "cell_px": [40.0, 40.0], "native_size": [12, 14]}
    assert np.array_equal(out[..., 3], sprite[..., 3])
    opaque = sprite[..., 3] == 255
    assert np.array_equal(nearest_sprite_color(out[opaque][:, :3]), nearest_sprite_color(sprite[opaque][:, :3]))


def test_pixelate_enlarges_by_a_whole_factor_only():
    # 12 x 14 blocks in a 40 x 40 canvas (38 x 38 inside the margin): x2 fits, x3 does not. Stretching would have
    # made it 33 x 38, some blocks 2 pixels and some 3.
    sprite = pixel_sprite()
    report = {}
    out = arr(pixelate(as_generated(sprite), 40, 40, 6, report=report))
    assert report["fit"] == "native" and report["scale"] == 2
    ys, xs = np.nonzero(out[..., 3])
    assert (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) == (8, 6, 32, 34)  # 24 x 28, centered
    subject = out[6:34, 8:32]
    assert np.array_equal(subject[::2, ::2], subject[1::2, 1::2])  # every pixel a 2 x 2 block
    assert np.array_equal(subject[::2, ::2, 3], sprite[1:15, 2:14, 3])


def test_pixelate_allows_slightly_uneven_block_sides():
    report = {}
    pixelate(drawn_in_blocks(pixel_sprite(), [40] * 16, [34] * 16), 16, 16, 6, report=report)
    assert report["fit"] == "native" and report["cell_px"] == [40.0, 34.0] and report["native_size"] == [12, 14]


def test_pixelate_stretches_uneven_blocks():
    # Blocks of 25-60 px at random, as Qwen sometimes draws without a reference image: no one grid fits them, so the
    # subject is stretched to fill the canvas as before.
    rng = np.random.default_rng(0)
    img = drawn_in_blocks(pixel_sprite(), rng.integers(25, 61, 16), rng.integers(25, 61, 16), seed=0)
    report = {}
    out = arr(pixelate(img, 16, 16, 6, report=report))
    assert report["fit"] == "stretch" and report["reason"] == "uneven grid"
    ys, xs = np.nonzero(out[..., 3])
    assert max(xs.max() - xs.min(), ys.max() - ys.min()) + 1 == 14  # fills the canvas minus the margin


def test_reference_ground():
    # Like the LAST LIGHT keeper: a 32x32 frame whose subject stands on row 28, stored enlarged 32x.
    keeper = np.zeros((32, 32, 4), np.uint8)
    keeper[3:29, 7:25] = (60, 70, 90, 255)
    stored = Image.fromarray(keeper, "RGBA").resize((1024, 1024), Image.Resampling.NEAREST)
    assert reference_ground(stored, 32) == 3
    assert reference_ground(stored, 24) == 2  # 3/32 of 24 rows, rounded
    keeper[29:, 7:25] = (60, 70, 90, 255)
    assert reference_ground(Image.fromarray(keeper, "RGBA"), 32) == 1  # never below the 1-cell margin
    floating = np.zeros((32, 32, 4), np.uint8)
    floating[2:12, 8:20] = (60, 70, 90, 255)
    assert reference_ground(Image.fromarray(floating, "RGBA"), 32) == 8  # at most a quarter of the canvas
    assert reference_ground(Image.new("RGBA", (32, 32)), 32) == 1  # nothing opaque


def test_pixelate_stands_sprites_on_the_ground():
    # ground=3, as from a keeper-like reference: the feet go on row height - 4, rebuilt or stretched.
    out = arr(pixelate(as_generated(pixel_sprite()), 40, 40, 6, anchor="bottom", ground=3))
    ys, _ = np.nonzero(out[..., 3])
    assert (ys.min(), ys.max()) == (9, 36)  # 14 blocks at x2 (the 36 rows above the ground hold x2, not x3)
    tall = np.zeros((600, 300, 4), np.uint8)
    tall[100:500, 100:200] = (200, 40, 40, 255)  # a plain shape: stretched into the rows above the ground
    out = arr(pixelate(Image.fromarray(tall, "RGBA"), 16, 16, 4, anchor="bottom", ground=3))
    ys, _ = np.nonzero(out[..., 3])
    assert (ys.min(), ys.max()) == (1, 12)
    centered = arr(pixelate(Image.fromarray(tall, "RGBA"), 16, 16, 4, ground=3))
    ys, _ = np.nonzero(centered[..., 3])
    assert (ys.min(), ys.max()) == (1, 14)  # a centered subject (an icon) keeps the 1-cell margin


def test_pixelate_squeezes_more_blocks_than_the_canvas_holds():
    rng = np.random.default_rng(5)
    sprite = np.zeros((22, 22, 4), np.uint8)
    sprite[1:21, 1:21, :3] = SPRITE_COLORS[rng.integers(0, len(SPRITE_COLORS), (20, 20))]
    sprite[1:21, 1:21, 3] = 255
    report = {}
    out = arr(pixelate(drawn_in_blocks(sprite, [40] * 22, [40] * 22), 16, 16, 6, report=report))
    assert report == {
        "fit": "stretch",
        "cell_px": [40.0, 40.0],
        "native_size": [20, 20],
        "reason": "larger than the canvas",
    }
    ys, xs = np.nonzero(out[..., 3])
    assert (xs.max() - xs.min() + 1, ys.max() - ys.min() + 1) == (14, 14)


def test_upscale_nearest():
    sprite = Image.fromarray(pixel_sprite(), "RGBA")
    big = upscale_nearest(sprite)
    assert big.size == (256, 256)
    assert np.array_equal(arr(big)[::16, ::16], pixel_sprite())  # whole blocks, no new colors
    assert upscale_nearest(Image.new("RGBA", (32, 20))).size == (256, 160)
    assert upscale_nearest(Image.new("RGBA", (300, 20))).size == (300, 20)


def test_process_image_with_spec():
    raw = generated(size=(1024, 1024), box=(300, 200, 700, 900), glass=None)
    report = {}
    sprite = process_image(raw, "sprite", pixel=PixelSpec(32, 32, 8), report=report)
    assert report["fit"] == "stretch"  # passed through to pixelate()
    assert sprite.size == (32, 32)
    assert set(np.unique(arr(sprite)[..., 3])) <= {0, 255}
    assert alpha_stats(sprite, band=1)["border_max"] == 0
    icon = process_image(raw, "icon", pixel=PixelSpec(16, 16, 8))
    assert icon.size == (16, 16)
    # icon_size shrinks the icon of a project that is not pixel art (user decision (c), 2026-09-25)
    shrunk = process_image(raw, "icon", icon_size=64)
    assert shrunk.size == (64, 64)
    assert alpha_stats(shrunk, band=1)["border_max"] == 0


def with_ring(img: Image.Image, center=(256, 256), radius=230, width=10) -> Image.Image:
    """Add a detached glass ring like Qwen's unrequested icon frame: alpha 60, a few short stretches at 150."""
    rgba = np.array(img)
    yy, xx = np.indices(rgba.shape[:2])
    r = np.hypot(yy - center[1], xx - center[0])
    ring = np.abs(r - radius) < width / 2
    rgba[ring] = (40, 50, 90, 60)
    rgba[ring & (np.abs(xx - center[0]) < 12)] = (40, 50, 90, 150)  # top and bottom stretches reach alpha 150
    return Image.fromarray(rgba, "RGBA")


def test_icon_drops_translucent_ring():
    raw = with_ring(generated(box=(176, 176, 336, 336), glass=None))  # a 160 px subject inside a 460 px ring
    icon = process_image(raw, "icon")
    assert icon.size == (160 + 2 * TRIM_PAD, 160 + 2 * TRIM_PAD)  # the canvas follows the subject, not the ring
    sprite = process_image(raw, "sprite")
    assert sprite.size[0] > 400  # sprites keep detached parts that have a core (unchanged behaviour)
    pixel_icon = arr(process_image(raw, "icon", pixel=PixelSpec(16, 16, 8)))
    ys, xs = np.nonzero(pixel_icon[..., 3])
    assert (xs.max() - xs.min() + 1, ys.max() - ys.min() + 1) == (14, 14)  # the subject fills the canvas


def test_pixelate_ignores_faint_halo():
    halo = np.zeros((400, 400, 4), np.uint8)
    halo[40:360, 40:360] = (90, 160, 255, 60)  # a faint glow, never opaque
    halo[150:250, 170:230] = (200, 40, 40, 255)  # 60 x 100 subject
    out = arr(pixelate(Image.fromarray(halo, "RGBA"), 16, 16, 4))
    ys, _ = np.nonzero(out[..., 3])
    assert ys.max() - ys.min() + 1 == 14  # fitted to the opaque subject, not to the halo


def test_icon_drops_opaque_frame_but_keeps_small_parts():
    raw = np.array(generated(box=(176, 176, 336, 336), glass=None))
    yy, xx = np.indices(raw.shape[:2])
    raw[np.abs(np.hypot(yy - 256, xx - 256) - 230) < 3] = (120, 20, 20, 255)  # a thin opaque circle, like 2026-09-25
    raw[120:140, 200:220] = (255, 240, 120, 255)  # a small solid sparkle above the subject, inside the circle
    icon = arr(process_image(Image.fromarray(raw, "RGBA"), "icon"))
    ys, xs = np.nonzero(icon[..., 3])
    height, width = ys.max() - ys.min() + 1, xs.max() - xs.min() + 1
    assert height < 400 and width < 400  # the circle is gone
    assert (icon[..., :3] == (255, 240, 120)).all(axis=-1).any()  # the sparkle stays
    sprite = arr(process_image(Image.fromarray(raw, "RGBA"), "sprite"))
    assert (sprite[..., :3] == (120, 20, 20)).all(axis=-1).any()  # sprites are left alone
