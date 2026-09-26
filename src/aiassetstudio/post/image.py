"""Post-processing for generated RGBA images: alpha cleanup, trimming, icon canvas, pixel-art cleanup, previews."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from PIL import Image
from scipy import ndimage

ALPHA_THRESHOLD = 16
CORE_ALPHA = 128  # a pixel group is part of the subject only if it has a solid core
MIN_CORE_PX = 16
BORDER_BAND = 32  # px band along the edges that alpha_stats() reports as border_mean / border_max
# The trim margin equals the border band, so a cleanly trimmed image reports border_mean 0.
# (The Phase 1 plan had pad=8 against the 32px band, which would flag every trimmed sprite.)
TRIM_PAD = BORDER_BAND
ICON_PAD_RATIO = 0.06
# Icons drop detached pieces that are mostly translucent. Qwen sometimes draws an unrequested glass ring around an
# item icon, in arcs of alpha up to ~170 with only 4-7% of their pixels at alpha >= 128 (2026-09-25 potion). Each
# arc passes the plain core test, and the trim then spans the whole ring.
ICON_MIN_CORE_SHARE = 0.25
FRAME_MAX_FILL = 0.2  # a detached shape filling less of its box than this, around the subject, is a frame
PREVIEW_MAX_SIDE = 256
PIXEL_MARGIN = 1  # empty cells around a pixelated subject
PIXEL_OPAQUE_ALPHA = 128  # a source pixel counts as opaque from this alpha on
# The model's own pixel grid. Qwen draws pixel art in blocks: about 32 px when the reference image is 32x32 pixel art
# enlarged to 1024, otherwise a size of its choosing, sometimes uneven. pixelate() rebuilds the subject one pixel per
# block and enlarges it by a whole factor only. Stretching it to fill the canvas made a block 1 or 2 pixels and bent
# small features (a slime's eyes, Phase 3 T3.C.2). Measured on 42 generated images, 2026-09-25: the thresholds keep
# every rebuild that looked right and none that looked wrong; the rest are stretched as before.
GRID_EDGE_STEP = 24  # channel step (premultiplied RGB or alpha) between neighbours that counts as an edge
GRID_CELL_MIN, GRID_CELL_MAX = 4.0, 128.0  # block sizes searched, in source px
GRID_STEP_UP = 0.6  # a multiple of the strongest block size wins while its regularity keeps this share
GRID_AXIS_SPREAD = 1.2  # each axis refines the shared block size within this factor (blocks are not quite square)
GRID_MIN_LINES = 6  # grid lines with an edge on them, per axis; fewer is no evidence of a grid (a plain rectangle)
GRID_MIN_REGULARITY = 0.5  # 0..1 per axis: how closely the edges line up on the grid
GRID_ASPECT = (0.8, 1.25)  # block width / height
GRID_MIXED_PURITY = 0.7  # a block is mixed when no one color (or transparency) covers this share of it
GRID_MAX_MIXED = 0.12  # at most this share of the subject's blocks may be mixed: more means the grid is off

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class PixelSpec:
    """What pixelate() produces: a width x height canvas with at most max_colors colors (from palette if given).
    `ground`: empty rows below a sprite's feet; the runner sets it from the project's reference image."""

    width: int
    height: int
    max_colors: int
    palette: tuple[RGB, ...] | None = None
    ground: int = PIXEL_MARGIN


def reference_ground(reference: Image.Image, height: int) -> int:
    """Empty rows below the subject of a reference image, as rows of a `height`-row canvas: where its sprites stand.

    The LAST LIGHT keeper stands on row 28 of its 32x32 frame, 3 empty rows below (every character of the game does);
    sprites put on the 1-cell margin stood 2 px lower. At least the margin, and at most a quarter of the canvas: a
    subject floating higher than that is not standing on the ground.
    """
    alpha = np.asarray(reference.convert("RGBA"))[..., 3]
    rows = np.flatnonzero((alpha >= PIXEL_OPAQUE_ALPHA).any(axis=1))
    if not len(rows):
        return PIXEL_MARGIN
    empty = (alpha.shape[0] - 1 - rows[-1]) / alpha.shape[0] * height
    return max(PIXEL_MARGIN, min(round(empty), height // 4))


def hex_to_rgb(color: str) -> RGB:
    value = color.strip().lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def clean_alpha(img: Image.Image, threshold: int = ALPHA_THRESHOLD) -> Image.Image:
    """Make near-transparent pixels (alpha < threshold) fully transparent, RGB included.

    Qwen leaves the background at alpha 1..8 instead of 0 (measured 2026-09-24). RGB is zeroed too so a
    game engine's bilinear filtering does not bleed the background colour into the edges when scaling.
    Genuinely translucent parts such as glass (alpha >= threshold) are kept as they are.
    """
    rgba = np.array(img.convert("RGBA"))
    rgba[rgba[..., 3] < threshold] = 0
    return Image.fromarray(rgba, "RGBA")


def drop_detached_faint(
    img: Image.Image,
    threshold: int = ALPHA_THRESHOLD,
    core: int = CORE_ALPHA,
    min_core_px: int = MIN_CORE_PX,
    min_core_share: float = 0.0,
) -> Image.Image:
    """Clear groups of pixels (alpha >= threshold, 8-connected) that have fewer than `min_core_px` pixels of
    alpha >= `core`, or whose core is less than `min_core_share` of the group. The group with the largest core
    (the subject) is always kept.

    Qwen sometimes leaves faint pixels a little above the cleanup threshold away from the subject, e.g. specks
    of alpha 16..21 along the frame edge of a translucent backdrop band (2026-09-25). They would widen the trim
    to the whole frame. Every real part of a subject has an opaque core; a faint glow attached to it is kept.
    `core` is capped at half the image's max alpha so an all-translucent subject (a ghost) survives.
    """
    rgba = np.array(img.convert("RGBA"))
    a = rgba[..., 3]
    core = min(core, int(a.max()) // 2)
    if core <= threshold:
        return Image.fromarray(rgba, "RGBA")
    labels, count = ndimage.label(a >= threshold, structure=np.ones((3, 3), bool))
    cores = np.bincount(labels[a >= core], minlength=count + 1)
    sizes = np.bincount(labels.ravel(), minlength=count + 1)
    keep = (cores >= min_core_px) & (cores >= min_core_share * sizes)
    if count:
        keep[1 + np.argmax(cores[1:])] = True
    keep[0] = False
    rgba[~keep[labels]] = 0
    return Image.fromarray(rgba, "RGBA")


def drop_surrounding_frames(img: Image.Image, max_fill: float = FRAME_MAX_FILL) -> Image.Image:
    """Clear detached thin shapes that surround the subject: rings and frames around an item icon.

    A group (alpha >= ALPHA_THRESHOLD, 8-connected) other than the subject is dropped when it covers less than
    `max_fill` of its bounding box and that box contains the subject's centre. The 2026-09-25 pixel-art potion came
    back inside an opaque 6 px circle: fill 0.08, box 1024x1022. Separate small parts (sparkles, a second coin) stay.
    """
    rgba = np.array(img.convert("RGBA"))
    a = rgba[..., 3]
    labels, count = ndimage.label(a >= ALPHA_THRESHOLD, structure=np.ones((3, 3), bool))
    if count < 2:
        return Image.fromarray(rgba, "RGBA")
    cores = np.bincount(labels[a >= min(CORE_ALPHA, int(a.max()) // 2)], minlength=count + 1)
    sizes = np.bincount(labels.ravel(), minlength=count + 1)
    boxes = ndimage.find_objects(labels)
    subject = 1 + int(np.argmax(cores[1:]))
    ys, xs = boxes[subject - 1]
    cy, cx = (ys.start + ys.stop) / 2, (xs.start + xs.stop) / 2
    for label, (ys, xs) in enumerate(boxes, start=1):
        area = (ys.stop - ys.start) * (xs.stop - xs.start)
        surrounds = ys.start <= cy < ys.stop and xs.start <= cx < xs.stop
        if label != subject and surrounds and sizes[label] < max_fill * area:
            rgba[labels == label] = 0
    return Image.fromarray(rgba, "RGBA")


def alpha_stats(img: Image.Image, band: int = BORDER_BAND) -> dict:
    """Share of transparent / opaque / partial pixels, and alpha along a `band`-px border."""
    a = np.asarray(img.convert("RGBA"))[..., 3]
    h, w = a.shape
    b = max(1, min(band, h // 2, w // 2))
    edge = np.concatenate([a[:b].ravel(), a[-b:].ravel(), a[b:-b, :b].ravel(), a[b:-b, -b:].ravel()])
    n = a.size
    return {
        "transparent": round(np.count_nonzero(a == 0) / n, 4),
        "opaque": round(np.count_nonzero(a == 255) / n, 4),
        "partial": round(np.count_nonzero((a > 0) & (a < 255)) / n, 4),
        "border_mean": round(float(edge.mean()), 6),
        "border_max": int(edge.max()),
        "border_band": b,
    }


def trim_to_content(img: Image.Image, pad: int = TRIM_PAD) -> Image.Image:
    """Crop to the bounding box of non-transparent pixels plus `pad` px, clamped to the image.

    The canvas is never enlarged, so a subject touching the frame edge still touches the edge afterwards
    (and shows up in border_mean) instead of being hidden behind added padding.
    """
    img = img.convert("RGBA")
    bbox = img.getchannel("A").getbbox()
    if bbox is None:
        return img.copy()
    left, top, right, bottom = bbox
    return img.crop((max(0, left - pad), max(0, top - pad), min(img.width, right + pad), min(img.height, bottom + pad)))


def square_canvas(img: Image.Image, pad_ratio: float = ICON_PAD_RATIO, min_pad: int = 0) -> Image.Image:
    """Center the image on a transparent square; the margin is `pad_ratio` of the longer side, at least `min_pad`."""
    longest = max(img.size)
    side = max(1, longest + 2 * max(min_pad, round(longest * pad_ratio)))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img.convert("RGBA"), ((side - img.width) // 2, (side - img.height) // 2))
    return canvas


def _color_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Squared "redmean" distance between RGB rows of a (n, 3) and b (m, 3): an (n, m) matrix. Closer to how far
    apart colors look than plain RGB distance, at the same cost."""
    a = a.astype(np.float64)[:, None, :]
    b = b.astype(np.float64)[None, :, :]
    rmean = (a[..., 0] + b[..., 0]) / 2
    d = (a - b) ** 2
    return (2 + rmean / 256) * d[..., 0] + 4 * d[..., 1] + (2 + (255 - rmean) / 256) * d[..., 2]


def _fold_colors(colors: np.ndarray, weights: np.ndarray, max_colors: int) -> np.ndarray:
    """For each of `colors` (n, 3), the index of the color it becomes so that at most `max_colors` of those with a
    nonzero weight (pixel count) remain.

    Repeatedly folds the rarer color of the closest pair into the other. Unlike a median cut, a small but distinct
    feature (glowing eyes) keeps its color because it is far from every other color, and no in-between colors
    appear; near-identical shades of one color are the closest pairs, so they fold together first.
    """
    target = np.arange(len(colors))
    weight = weights.astype(np.float64).copy()
    distance = _color_distance(colors, colors)
    np.fill_diagonal(distance, np.inf)
    unused = weight <= 0
    distance[unused, :] = np.inf
    distance[:, unused] = np.inf
    alive = int(np.count_nonzero(~unused))
    while alive > max_colors:
        i, j = np.unravel_index(np.argmin(distance), distance.shape)
        keep, drop = (i, j) if weight[i] >= weight[j] else (j, i)
        weight[keep] += weight[drop]
        target[target == drop] = keep
        distance[drop, :] = np.inf
        distance[:, drop] = np.inf
        alive -= 1
    return target


def _final_colors(
    rgb: np.ndarray, max_colors: int, palette: tuple[RGB, ...] | list[RGB] | None
) -> tuple[np.ndarray, np.ndarray]:
    """The colors pixel art of these (n, 3) source pixels uses, and each pixel's color index.

    Chosen once for the whole image: up to 256 shades (median cut), snapped to the palette if there is one, then
    folded down to max_colors. Choosing them before the cells vote keeps one color's votes together; voting among
    finer shades first let a split majority lose its cell.
    """
    shades_img = Image.fromarray(rgb.reshape(1, -1, 3), "RGB").quantize(
        colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )
    shade = np.asarray(shades_img).ravel().astype(np.int64)
    n_shades = int(shade.max()) + 1
    shades = np.array(shades_img.getpalette()[: 3 * n_shades], np.uint8).reshape(-1, 3)
    if palette:
        colors = np.array(palette, np.uint8).reshape(-1, 3)
        shade_color = _color_distance(shades, colors).argmin(axis=1)
    else:
        colors = shades
        shade_color = np.arange(n_shades)
    pixel_color = shade_color[shade]
    pixel_color = _fold_colors(colors, np.bincount(pixel_color, minlength=len(colors)), max_colors)[pixel_color]
    final, pixel_color = np.unique(pixel_color, return_inverse=True)  # compact ids 0..len(final)-1
    return colors[final], pixel_color.ravel()


def _vote(
    cell: np.ndarray, n_cells: int, opaque: np.ndarray, pixel_color: np.ndarray, n_colors: int
) -> tuple[np.ndarray, np.ndarray]:
    """Per cell of `cell` (a cell index for every source pixel): its pixel count and its opaque pixels per color."""
    total = np.bincount(cell.ravel(), minlength=n_cells)
    votes = np.bincount(cell[opaque] * n_colors + pixel_color, minlength=n_cells * n_colors)
    return total, votes.reshape(n_cells, n_colors)


def _cells_to_rgba(total: np.ndarray, votes: np.ndarray, colors: np.ndarray) -> np.ndarray:
    """Each cell: opaque if at least half its source pixels are, colored by the majority of those. (n_cells, 4)."""
    filled = votes.sum(axis=1) * 2 >= total
    out = np.zeros((len(total), 4), np.uint8)
    out[filled, :3] = colors[votes[filled].argmax(axis=1)]
    out[filled, 3] = 255
    return out


def _place(canvas: np.ndarray, grid: np.ndarray, anchor: Literal["center", "bottom"], ground: int) -> Image.Image:
    height, width = canvas.shape[:2]
    grid_h, grid_w = grid.shape[:2]
    left = (width - grid_w) // 2
    top = height - ground - grid_h if anchor == "bottom" else (height - grid_h) // 2
    canvas[top : top + grid_h, left : left + grid_w] = grid
    return Image.fromarray(canvas, "RGBA")


@dataclass(frozen=True)
class GridAxis:
    """The model's block grid along one axis: lines at phase + i * size, in source px."""

    size: float
    phase: float
    regularity: float  # 0..1: how closely the edges line up on one phase of this block size
    lines: int  # grid lines across the subject that an edge lies on


def _edge_projection(rgba: np.ndarray, axis: int) -> np.ndarray:
    """Edges between each pixel and the next along `axis` (1: across columns, 0: across rows), counted over the other
    axis. Only the strongest step of a blurred edge counts, so each edge has one position."""
    alpha = rgba[..., 3:4].astype(np.int16)
    img = np.concatenate([rgba[..., :3].astype(np.int16) * alpha // 255, alpha], axis=-1)
    step = np.abs(np.diff(img, axis=axis)).max(axis=-1)
    if axis == 0:
        step = step.T
    before = np.pad(step, ((0, 0), (1, 0)))[:, :-1]
    after = np.pad(step, ((0, 0), (0, 1)))[:, 1:]
    return ((step >= GRID_EDGE_STEP) & (step >= before) & (step > after)).sum(axis=0).astype(np.float64)


def _periodogram(edges: np.ndarray, sizes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each block size: the regularity of the edges (the resultant length of their positions taken as angles of
    that period, 0..1) and the phase they agree on, in px."""
    position = np.arange(len(edges)) + 1.0  # edge i lies between pixels i and i + 1
    turns = np.exp(2j * np.pi * position[:, None] / sizes[None, :]).astype(np.complex64)
    z = (edges / edges.sum()).astype(np.float32) @ turns
    return np.abs(z), np.angle(z) % (2 * np.pi) / (2 * np.pi) * sizes


def _segment_impurity(ids: np.ndarray, size: float, phase: float) -> float:
    """Share of pixels whose color id differs from the majority of their row within the same block column."""
    h, w = ids.shape
    column = np.floor((np.arange(w) - phase) / size).astype(np.int64)
    column -= column[0]
    n, c = int(column[-1]) + 1, int(ids.max()) + 1
    counts = np.bincount(((np.arange(h)[:, None] * n + column) * c + ids).ravel(), minlength=h * n * c)
    return 1.0 - counts.reshape(h * n, c).max(axis=1).sum() / ids.size


def _grid_axis(
    edges: np.ndarray, rho: np.ndarray, phase: np.ndarray, sizes: np.ndarray, shared: float, ids: np.ndarray, empty: int
) -> GridAxis:
    """Refine the shared block size along the columns of `ids` (color ids, `empty` for transparent) and choose the
    phase that leaves each block column most uniform: the one the edges agree on, a line at either end of the
    subject, or a whole number of blocks spread evenly over it (Qwen's blocks drift a little)."""
    occupied = np.flatnonzero((ids != empty).any(axis=0))
    lo, hi = int(occupied[0]), int(occupied[-1]) + 1
    near = np.flatnonzero((sizes >= shared / GRID_AXIS_SPREAD) & (sizes <= shared * GRID_AXIS_SPREAD))
    j = int(near[np.argmax(rho[near])])
    size = float(sizes[j])
    even = (hi - lo) / max(1, round((hi - lo) / size))
    candidates = [(size, float(phase[j])), (size, lo % size), (size, hi % size), (even, lo % even)]
    size, ph = min(candidates, key=lambda c: _segment_impurity(ids, *c))
    lines = ph + np.arange(np.ceil((lo - ph) / size), np.floor((hi - ph) / size) + 1) * size
    at = np.flatnonzero(edges) + 1.0
    hit = (np.abs(at[None, :] - lines[:, None]) <= max(1.0, 0.15 * size)).any(axis=1)
    return GridAxis(size, ph, float(rho[j]), int(hit.sum()))


def find_pixel_grid(rgba: np.ndarray, ids: np.ndarray, empty: int) -> tuple[GridAxis, GridAxis] | None:
    """The model's block grid of a generated pixel-art image (columns, rows), or None if it has no edges.

    `ids`: a color id per pixel, `empty` for transparent ones. Edges on the true grid also lie on the grid of any
    whole fraction of its size, so regularity is as high at size / 2, size / 3 ... and low at its multiples: from
    the strongest block size (both axes together), step up to the largest multiple that keeps most of it.
    """
    edges = [_edge_projection(rgba, 1), _edge_projection(rgba, 0)]
    if not all(e.any() for e in edges):
        return None
    sizes = np.exp(np.arange(np.log(GRID_CELL_MIN), np.log(GRID_CELL_MAX), 0.002))
    grams = [_periodogram(e, sizes) for e in edges]
    joint = (grams[0][0] + grams[1][0]) / 2
    best = chosen = int(np.argmax(joint))
    for m in range(2, int(GRID_CELL_MAX // sizes[best]) + 1):
        near = np.flatnonzero(np.abs(sizes / (m * sizes[best]) - 1) <= 0.03)
        if len(near) and joint[near].max() >= GRID_STEP_UP * joint[best]:
            chosen = int(near[np.argmax(joint[near])])
    shared = float(sizes[chosen])
    return (
        _grid_axis(edges[0], *grams[0], sizes, shared, ids, empty),
        _grid_axis(edges[1], *grams[1], sizes, shared, ids.T, empty),
    )


def _native_pixels(
    rgba: np.ndarray, opaque: np.ndarray, colors: np.ndarray, pixel_color: np.ndarray
) -> tuple[np.ndarray | None, dict]:
    """The subject rebuilt one pixel per model block, cropped to it (an RGBA array), or None when the image has no
    regular grid. Also a report: block size, rebuilt size, and why it was not used."""
    empty = len(colors)
    ids = np.full(opaque.shape, empty, np.int64)
    ids[opaque] = pixel_color
    grid = find_pixel_grid(rgba, ids, empty)
    if grid is None:
        return None, {"reason": "no grid"}
    gx, gy = grid
    h, w = opaque.shape
    col = np.floor((np.arange(w) - gx.phase) / gx.size).astype(np.int64)
    row = np.floor((np.arange(h) - gy.phase) / gy.size).astype(np.int64)
    col, row = col - col[0], row - row[0]
    nw, nh = int(col[-1]) + 1, int(row[-1]) + 1
    total, votes = _vote(row[:, None] * nw + col[None, :], nw * nh, opaque, pixel_color, empty)
    cells = _cells_to_rgba(total, votes, colors).reshape(nh, nw, 4)
    ys, xs = np.nonzero(cells[..., 3])
    if min(gx.lines, gy.lines) < GRID_MIN_LINES or not len(ys):
        return None, {"reason": "no grid"}
    cells = cells[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    report = {"cell_px": [round(gx.size, 1), round(gy.size, 1)], "native_size": [cells.shape[1], cells.shape[0]]}
    in_subject = votes.sum(axis=1) > 0
    main = np.maximum(votes.max(axis=1), total - votes.sum(axis=1))[in_subject] / total[in_subject]
    regular = min(gx.regularity, gy.regularity) >= GRID_MIN_REGULARITY
    square = GRID_ASPECT[0] <= gx.size / gy.size <= GRID_ASPECT[1]
    if not (regular and square and np.mean(main < GRID_MIXED_PURITY) <= GRID_MAX_MIXED):
        return None, report | {"reason": "uneven grid"}
    return cells, report


def pixelate(
    img: Image.Image,
    width: int,
    height: int,
    max_colors: int,
    palette: tuple[RGB, ...] | list[RGB] | None = None,
    anchor: Literal["center", "bottom"] = "center",
    report: dict | None = None,
    ground: int = PIXEL_MARGIN,
) -> Image.Image:
    """Clean a generated image up into width x height pixel art: at most max_colors colors (all from `palette` if
    given) and alpha 0 or 255 only.

    If the model drew on a regular grid of blocks, the subject is rebuilt one pixel per block and enlarged by the
    largest whole factor that fits the canvas minus a 1-cell margin (x1 included, so it may not fill the canvas).
    Otherwise, or if it has more blocks than the canvas holds, the trimmed subject is stretched to fit, keeping its
    aspect ratio. Either way each cell takes the final color most of its source pixels map to, the colors being
    chosen from the whole image first. Picking one sample per cell (plain nearest-neighbour) is not enough: Qwen's
    blocks are not all the same size, so single samples blur edges and scatter specks. `anchor` places the subject;
    "bottom" stands every sprite on the same row, `ground` empty rows above the bottom edge (instead of the margin).

    `report`, if given, is filled with how the subject was fitted: "fit" ("native" or "stretch"), "cell_px" (block
    width and height in source px) and "native_size" when a grid was found, "scale" (native) or "reason" (stretch).
    """
    ground = ground if anchor == "bottom" else PIXEL_MARGIN
    report = {} if report is None else report
    canvas = np.zeros((height, width, 4), np.uint8)
    rgba = np.asarray(clean_alpha(img))
    opaque = rgba[..., 3] >= PIXEL_OPAQUE_ALPHA
    if not opaque.any():
        report.update(fit="stretch", reason="empty")
        return Image.fromarray(canvas, "RGBA")
    colors, pixel_color = _final_colors(rgba[opaque][:, :3], max_colors, palette)
    inner_w, inner_h = width - 2 * PIXEL_MARGIN, height - PIXEL_MARGIN - ground

    native, found = _native_pixels(rgba, opaque, colors, pixel_color)
    if native is not None:
        scale = min(inner_w // native.shape[1], inner_h // native.shape[0])
        if scale >= 1:
            report.update(fit="native", scale=scale, **found)
            return _place(canvas, native.repeat(scale, axis=0).repeat(scale, axis=1), anchor, ground)
        found["reason"] = "larger than the canvas"
    report.update(fit="stretch", **found)

    # Trim to the opaque pixels: fainter ones never become output pixels, so a faint halo must not shrink the subject.
    # (The opaque pixels keep their order, so pixel_color still lines up with them.)
    ys, xs = np.nonzero(opaque)
    opaque = opaque[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    # Cell grid: the subject scaled to fit inside the margin, aspect ratio kept.
    h, w = opaque.shape
    scale = min(inner_w / w, inner_h / h)
    grid_w = min(inner_w, max(1, round(w * scale)))
    grid_h = min(inner_h, max(1, round(h * scale)))
    cell = (np.arange(h) * grid_h // h)[:, None] * grid_w + (np.arange(w) * grid_w // w)[None, :]
    total, votes = _vote(cell, grid_w * grid_h, opaque, pixel_color, len(colors))
    return _place(canvas, _cells_to_rgba(total, votes, colors).reshape(grid_h, grid_w, 4), anchor, ground)


def colors_used(img: Image.Image) -> int:
    """Distinct colors among the opaque pixels."""
    rgba = np.asarray(img.convert("RGBA"))
    return len(np.unique(rgba[rgba[..., 3] > 0][:, :3], axis=0))


def upscale_nearest(img: Image.Image, max_side: int = PREVIEW_MAX_SIDE) -> Image.Image:
    """Enlarge by the largest whole factor that fits in max_side (at least 1), nearest-neighbour: pixel-art preview."""
    factor = max(1, max_side // max(img.size))
    return img.resize((img.width * factor, img.height * factor), Image.Resampling.NEAREST)


def make_preview(img: Image.Image, max_side: int = PREVIEW_MAX_SIDE) -> Image.Image:
    longest = max(img.size)
    if longest <= max_side:
        return img.copy()
    scale = max_side / longest
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(size, Image.Resampling.LANCZOS)  # Pillow premultiplies RGBA while resampling


def postprocess_settings(kind: str, pixel: PixelSpec | None = None, icon_size: int | None = None) -> dict:
    """Settings recorded in asset meta so a result can be reproduced."""
    settings = {
        "alpha_threshold": ALPHA_THRESHOLD,
        "core_alpha": CORE_ALPHA,
        "min_core_px": MIN_CORE_PX,
        "trim_pad": TRIM_PAD,
        "preview_max_side": PREVIEW_MAX_SIDE,
    }
    if kind == "icon":
        settings |= {"min_core_share": ICON_MIN_CORE_SHARE, "frame_max_fill": FRAME_MAX_FILL}
    if pixel is not None:
        return settings | {
            "trim_pad": 0,
            "pixelate": {
                "width": pixel.width,
                "height": pixel.height,
                "max_colors": pixel.max_colors,
                "palette": [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in pixel.palette] if pixel.palette else None,
                "margin": PIXEL_MARGIN,
                "opaque_alpha": PIXEL_OPAQUE_ALPHA,
                "anchor": _pixel_anchor(kind),
                **({"ground": pixel.ground} if _pixel_anchor(kind) == "bottom" else {}),
                "fit": "model grid at a whole factor, else stretch",
                "grid": {
                    "edge_step": GRID_EDGE_STEP,
                    "cell_px": [GRID_CELL_MIN, GRID_CELL_MAX],
                    "step_up": GRID_STEP_UP,
                    "axis_spread": GRID_AXIS_SPREAD,
                    "min_lines": GRID_MIN_LINES,
                    "min_regularity": GRID_MIN_REGULARITY,
                    "aspect": list(GRID_ASPECT),
                    "mixed_purity": GRID_MIXED_PURITY,
                    "max_mixed": GRID_MAX_MIXED,
                },
            },
            "preview": "nearest",
        }
    if kind == "icon":
        settings |= {"trim_pad": 0, "icon_pad_ratio": ICON_PAD_RATIO, "icon_min_pad": TRIM_PAD}
        if icon_size:
            settings["icon_size"] = icon_size
    return settings


def _pixel_anchor(kind: str) -> Literal["center", "bottom"]:
    # Sprites stand on the bottom margin row, so every sprite's feet line up in the game; icons are centered.
    return "bottom" if kind == "sprite" else "center"


def process_image(
    raw: Image.Image,
    kind: str,
    pixel: PixelSpec | None = None,
    icon_size: int | None = None,
    report: dict | None = None,
) -> Image.Image:
    """`pixel`: clean up into pixel art of that spec (for an icon, the caller passes the icon's square spec).
    `icon_size`: shrink a non-pixel icon to that square size (user decision (c), 2026-09-25).
    `report`: filled by pixelate() with how a pixel-art subject was fitted."""
    if kind not in ("sprite", "icon"):
        raise ValueError(f"unknown image kind {kind!r}")
    min_core_share = ICON_MIN_CORE_SHARE if kind == "icon" else 0.0
    img = drop_detached_faint(clean_alpha(raw), min_core_share=min_core_share)
    if kind == "icon":
        img = drop_surrounding_frames(img)
    if pixel is not None:
        return pixelate(
            img,
            pixel.width,
            pixel.height,
            pixel.max_colors,
            pixel.palette,
            _pixel_anchor(kind),
            report=report,
            ground=pixel.ground,
        )
    if kind == "sprite":
        return trim_to_content(img)
    # Icons: trim tight, then one margin of 6% of the longer side (at least the 32 px border band).
    # Trimming with TRIM_PAD first added a second margin (the 2026-09-25 test icon: 959 px instead of 888).
    icon = square_canvas(trim_to_content(img, pad=0), min_pad=TRIM_PAD)
    if icon_size:
        icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
    return icon


def processed_border_band(pixel: PixelSpec | None, icon_size: int | None) -> int:
    """Border band for alpha_stats() of a processed image: its margin is one pixel when it was shrunk to a spec."""
    return 1 if pixel is not None or icon_size else BORDER_BAND
