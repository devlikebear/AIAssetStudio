"""Animation frames in a game's pixel-art spec: the base sprite's size, feet row and colors in every frame.

sprite-gen extracts codex's rows at the pixel size codex drew, a finer grid than the base sprite's (33-40 rows for a
26-row sprite in the 2026-09-25 trial, docs/plans/notes/animation-trial.md). Each row is shrunk here until its median
height is the base sprite's, every output pixel taking the dominant color of its block the way sprite-gen's kCentroid
downscale does, so 1 px outlines and eyes survive. Then every frame stands on the project's feet row, and the frames
are recolored together to the base sprite's colors (snapped to the project's palette if it has one).
"""

import io
import json
import statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .image import PIXEL_OPAQUE_ALPHA, RGB, PixelSpec, _color_distance


@dataclass(frozen=True)
class Row:
    state: str  # sprite-gen's state name
    tag: str  # the game's animation tag
    frames: int
    seconds: float  # per frame
    action: str  # what sprite-gen asks codex to draw


# LAST LIGHT's enemy rows (Tools/build_campaign_art.py, Tools/archive_campaign_art.lua): 10 frames, idle 1-4 at
# 0.18 s, then walk 5-10 at 0.1 s. The actions are the ones the 2026-09-25 trial used.
ROWS = (
    Row("idle", "idle", 4, 0.18, "subtle breathing and blinking"),
    Row("frontwalk", "walk", 6, 0.1, "creeping walk toward the viewer"),
)
FRAMES = sum(r.frames for r in ROWS)
NATIVE_CELL_FACTOR = 2  # sprite-gen extracts into cells this much larger, so its size cap never shrinks a row
SIZE_TOLERANCE = (2, 1)  # idle frames within this many cells of the base sprite's width and height count as its size
MIN_FACTOR = 0.5  # a row shrunk more than this loses detail
LUMA = np.array([299, 587, 114])


def game_tags() -> list[dict]:
    """The game's tags: first and last frame (0-based, inclusive) and seconds per frame."""
    tags, start = [], 0
    for r in ROWS:
        tags.append({"name": r.tag, "from": start, "to": start + r.frames - 1, "duration": r.seconds})
        start += r.frames
    return tags


def request_states() -> dict[str, dict]:
    """The states of the sprite-gen request: one row per game tag."""
    return {r.state: {"frames": r.frames, "fps": round(1 / r.seconds), "loop": True, "action": r.action} for r in ROWS}


def load_frames(run_dir: Path) -> dict[str, list[Image.Image]]:
    """Each row's frames, cut out of sprite-gen's atlas by its manifest.json (frame_layout.rows)."""
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = (manifest.get("frame_layout") or {}).get("rows") or {}
    with Image.open(run_dir / manifest.get("sprite_sheet_alpha", "sprite-sheet-alpha.png")) as img:
        atlas = img.convert("RGBA")
    frames = {}
    for r in ROWS:
        rects = rows.get(r.state) or []
        if len(rects) != r.frames:
            raise ValueError(f"sprite-gen made {len(rects)} {r.state} frames instead of {r.frames} ({manifest_path})")
        frames[r.state] = [atlas.crop((c["x"], c["y"], c["x"] + c["w"], c["y"] + c["h"])) for c in rects]
    return frames


def _box(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Opaque pixels' left, top, right, bottom (right and bottom inclusive)."""
    opaque = np.asarray(img.convert("RGBA"))[..., 3] >= PIXEL_OPAQUE_ALPHA
    ys, xs = np.nonzero(opaque)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(ys) else None


def _size(box: tuple[int, int, int, int]) -> list[int]:
    return [box[2] - box[0] + 1, box[3] - box[1] + 1]


def _block_color(px: np.ndarray) -> np.ndarray:
    """The color a block of opaque (n, 3) pixels becomes, as in sprite-gen's kCentroid downscale: two clusters grown
    from the darkest and the lightest pixel, the larger wins, but a dark cluster of 40% or more that is far darker than
    the other wins too (outlines and eyes survive). Its most common color, not its mean: no new colors appear."""
    if (px == px[0]).all():
        return px[0]
    px = px.astype(np.int64)
    luma = px @ LUMA
    centroids = np.stack([px[luma.argmin()], px[luma.argmax()]])
    for _ in range(3):
        distance = ((px[:, None, :] - centroids[None]) ** 2).sum(axis=2)
        assign = (distance[:, 1] < distance[:, 0]).astype(np.int64)
        for k in (0, 1):
            if (assign == k).any():
                centroids[k] = px[assign == k].sum(axis=0) // (assign == k).sum()
    counts = np.bincount(assign, minlength=2)
    pick = 0 if counts[0] >= counts[1] else 1
    c_luma = centroids @ LUMA
    darker = int(c_luma.argmin())
    if (
        darker != pick
        and counts[darker] / len(px) >= 0.40
        and c_luma[darker] < 70000
        and c_luma[1 - darker] - c_luma[darker] > 50000
    ):
        pick = darker
    colors, n = np.unique(px[assign == pick], axis=0, return_counts=True)
    return colors[n.argmax()]


def shrink(img: Image.Image, width: int, height: int) -> Image.Image:
    """Pixel art shrunk to width x height: a pixel is opaque if half its source block is, colored by _block_color."""
    src = np.asarray(img.convert("RGBA"))
    opaque = src[..., 3] >= PIXEL_OPAQUE_ALPHA
    sh, sw = opaque.shape
    ys = [(oy * sh // height, max(oy * sh // height + 1, (oy + 1) * sh // height)) for oy in range(height)]
    xs = [(ox * sw // width, max(ox * sw // width + 1, (ox + 1) * sw // width)) for ox in range(width)]
    out = np.zeros((height, width, 4), np.uint8)
    for oy, (y0, y1) in enumerate(ys):
        if not opaque[y0:y1].any():
            continue
        for ox, (x0, x1) in enumerate(xs):
            block = opaque[y0:y1, x0:x1]
            if block.sum() * 2 < block.size:
                continue
            out[oy, ox, :3] = _block_color(src[y0:y1, x0:x1][block][:, :3])
            out[oy, ox, 3] = 255
    return Image.fromarray(out, "RGBA")


def target_colors(base: Image.Image, palette: tuple[RGB, ...] | None) -> np.ndarray:
    """The colors animation frames may use: the base sprite's own, snapped to the palette if there is one. (n, 3)"""
    rgba = np.asarray(base.convert("RGBA"))
    colors = np.unique(rgba[rgba[..., 3] >= PIXEL_OPAQUE_ALPHA][:, :3], axis=0)
    if palette:
        allowed = np.array(palette, np.uint8).reshape(-1, 3)
        colors = np.unique(allowed[_color_distance(colors, allowed).argmin(axis=1)], axis=0)
    return colors


def recolor(frames: list[Image.Image], colors: np.ndarray) -> list[Image.Image]:
    """Every frame's pixels in the nearest of `colors`, one mapping for all frames (so no color flickers)."""
    stack = np.stack([np.asarray(f.convert("RGBA")) for f in frames]).copy()
    opaque = stack[..., 3] >= PIXEL_OPAQUE_ALPHA
    stack[..., 3] = np.where(opaque, 255, 0)
    stack[~opaque, :3] = 0
    found, inverse = np.unique(stack[opaque][:, :3], axis=0, return_inverse=True)
    if len(found):
        nearest = _color_distance(found, colors).argmin(axis=1)
        stack[opaque, :3] = colors[nearest][inverse.ravel()]
    return [Image.fromarray(frame, "RGBA") for frame in stack]


def fit_frames(
    frames: dict[str, list[Image.Image]], spec: PixelSpec, base: Image.Image
) -> tuple[list[Image.Image], dict]:
    """The FRAMES frames, idle then walk, on spec's canvas, and a report of what was done.

    `frames` are sprite-gen's, at the size codex drew them; `base` is the sprite they animate. The report has
    base_size, frame_sizes, per-row factor and median size, idle_size and walk_size (median w x h), idle_height,
    size_ok (idle within SIZE_TOLERANCE of the base), ground_row, colors_used and warnings.
    """
    base_box = _box(base)
    if base_box is None:
        raise ValueError("the base sprite has no opaque pixels")
    base_w, base_h = _size(base_box)
    feet = spec.height - spec.ground - 1
    fitted: list[Image.Image] = []
    rows: dict[str, dict] = {}
    warnings: list[str] = []
    for r in ROWS:
        boxes = [_box(f) for f in frames[r.state]]
        if None in boxes:
            raise ValueError(f"sprite-gen made an empty {r.state} frame")
        native_h = statistics.median(b[3] - b[1] + 1 for b in boxes)
        # The median height becomes the base's, unless the tallest frame (or the row, side to side) would not fit
        # above the feet row: then a little smaller, rather than cutting a frame.
        room = min(
            (feet + 1) / max(b[3] - b[1] + 1 for b in boxes),
            spec.width / (max(b[2] for b in boxes) + 1 - min(b[0] for b in boxes)),
        )
        factor = min(1.0, base_h / native_h, room)
        if factor < MIN_FACTOR:
            warnings.append(f"{r.tag}: codex drew it {native_h:g} rows tall; shrunk {factor:.2f}x, details may be lost")
        if factor < 1:
            cell_w, cell_h = frames[r.state][0].size
            size = (max(1, round(cell_w * factor)), max(1, round(cell_h * factor)))
            row = [shrink(f, *size) for f in frames[r.state]]  # whole cells: frames keep their places in the row
        else:
            row = list(frames[r.state])
        boxes = [_box(f) for f in row]
        if None in boxes:
            raise ValueError(f"a {r.state} frame vanished when shrunk {factor:.2f}x")
        center = (min(b[0] for b in boxes) + max(b[2] for b in boxes) + 1) / 2
        left = round(spec.width / 2 - center)  # the row's middle on the canvas's middle
        for i, (frame, box) in enumerate(zip(row, boxes)):
            top = feet - box[3]  # every frame stands on the feet row
            if box[0] + left < 0 or box[2] + left >= spec.width or box[1] + top < 0:
                warnings.append(
                    f"{r.tag} frame {i}: larger than the {spec.width}x{spec.height} canvas, cut at its edge"
                )
            canvas = Image.new("RGBA", (spec.width, spec.height))
            canvas.paste(frame, (left, top), frame)
            fitted.append(canvas)
        rows[r.tag] = {"state": r.state, "native_height": native_h, "factor": round(factor, 3)}
        if room < min(1.0, base_h / native_h):
            rows[r.tag]["fitted_to_canvas"] = True
    fitted = recolor(fitted, target_colors(base, spec.palette))

    sizes = [_size(_box(f)) for f in fitted]
    start = 0
    for r in ROWS:
        part = sizes[start : start + r.frames]
        rows[r.tag]["size"] = [statistics.median(s[0] for s in part), statistics.median(s[1] for s in part)]
        start += r.frames
    idle_w, idle_h = rows["idle"]["size"]
    stack = np.stack([np.asarray(f) for f in fitted])
    report = {
        "base_size": [base_w, base_h],
        "frame_sizes": sizes,
        "rows": rows,
        "idle_size": rows["idle"]["size"],
        "walk_size": rows["walk"]["size"],
        "idle_height": idle_h,
        "size_ok": abs(idle_w - base_w) <= SIZE_TOLERANCE[0] and abs(idle_h - base_h) <= SIZE_TOLERANCE[1],
        "ground_row": feet,
        "colors_used": len(np.unique(stack[stack[..., 3] == 255][:, :3], axis=0)),
        "warnings": warnings,
    }
    return fitted, report


def game_row(frames: list[Image.Image]) -> Image.Image:
    """The frames side by side in one row: the game's sheet of one character (320x32 for 10 frames of 32x32)."""
    w, h = frames[0].size
    row = Image.new("RGBA", (w * len(frames), h))
    for i, frame in enumerate(frames):
        row.paste(frame, (i * w, 0))
    return row


def game_json(width: int, height: int, name: str) -> dict:
    """What the game needs besides the PNG: frame size and the tags (Aseprite-style, 0-based and inclusive)."""
    return {
        "name": name,
        "image": f"{name}.png",
        "frame_width": width,
        "frame_height": height,
        "frames": FRAMES,
        "tags": game_tags(),
    }


def _checker(width: int, height: int, cell: int) -> Image.Image:
    ys, xs = np.mgrid[0:height, 0:width]
    light = ((ys // cell + xs // cell) % 2).astype(bool)
    rgb = np.where(light[..., None], np.uint8(205), np.uint8(175)).repeat(3, axis=2)
    return Image.fromarray(np.dstack([rgb, np.full((height, width), 255, np.uint8)]), "RGBA")


def contact_sheet(frames: list[Image.Image], ground_row: int, zoom: int = 4) -> Image.Image:
    """All frames in a row at `zoom`x on a checkerboard, numbered, with a red line under the feet row: the preview
    get_job returns (Claude looks at it) and the gallery shows."""
    w, h = frames[0].size
    gap, label = 4, 14
    sheet = Image.new("RGBA", (len(frames) * (w * zoom + gap) + gap, h * zoom + label + gap), (255, 255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    tags = {t["from"] + i: (t["name"], i) for t in game_tags() for i in range(t["to"] - t["from"] + 1)}
    for i, frame in enumerate(frames):
        x = gap + i * (w * zoom + gap)
        tile = _checker(w * zoom, h * zoom, 2 * zoom)
        tile.alpha_composite(frame.resize((w * zoom, h * zoom), Image.Resampling.NEAREST))
        sheet.paste(tile, (x, label))
        line = label + (ground_row + 1) * zoom
        draw.line([(x, line), (x + w * zoom - 1, line)], fill=(220, 60, 60, 255))
        tag, n = tags.get(i, ("", 0))
        draw.text((x, 1), f"{i} {tag} {n + 1}", fill=(60, 60, 60, 255), font=font)
    return sheet


def animated_gif(frames: list[Image.Image], zoom: int = 4) -> bytes:
    """The frames at `zoom`x as a looping GIF in the game's timing, transparent around the sprite."""
    stack = np.stack([np.asarray(f.convert("RGBA")) for f in frames])
    opaque = stack[..., 3] == 255
    colors, inverse = np.unique(stack[opaque][:, :3], axis=0, return_inverse=True)
    if len(colors) > 255:
        raise ValueError(f"{len(colors)} colors do not fit a GIF")
    index = np.zeros(stack.shape[:3], np.uint8)  # 0 = transparent
    index[opaque] = inverse.ravel() + 1
    palette = [0, 0, 0, *colors.astype(int).ravel().tolist()]
    durations = [round(t["duration"] * 1000) for t in game_tags() for _ in range(t["to"] - t["from"] + 1)]
    images = []
    for frame in index:
        img = Image.fromarray(frame, "P")
        img.putpalette(palette)
        images.append(img.resize((img.width * zoom, img.height * zoom), Image.Resampling.NEAREST))
    buffer = io.BytesIO()
    images[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=durations[: len(images)],
        loop=0,
        transparency=0,
        disposal=2,
        optimize=False,
    )
    return buffer.getvalue()
