import io
import json

import numpy as np
import pytest
from PIL import Image

from aiassetstudio.post import animation
from aiassetstudio.post.animation import (
    FRAMES,
    ROWS,
    animated_gif,
    contact_sheet,
    fit_frames,
    game_json,
    game_row,
    load_frames,
    request_states,
    shrink,
)
from aiassetstudio.post.image import PixelSpec

BODY, OUTLINE, EYE = (40, 40, 70), (10, 10, 20), (250, 230, 150)
SPEC = PixelSpec(32, 32, 12, ground=3)  # feet on row 28, like LAST LIGHT


def sprite(w: int, h: int, scale: int = 1, body=BODY) -> Image.Image:
    """A w x h creature (body, 1-cell outline, two eyes), drawn with scale x scale blocks."""
    a = np.zeros((h, w, 4), np.uint8)
    a[:, :] = (*OUTLINE, 255)
    a[1:-1, 1:-1] = (*body, 255)
    a[h // 3, w // 4] = a[h // 3, w - 1 - w // 4] = (*EYE, 255)
    return Image.fromarray(a.repeat(scale, axis=0).repeat(scale, axis=1), "RGBA")


def place(img: Image.Image, cell: int, left: int, bottom: int) -> Image.Image:
    canvas = Image.new("RGBA", (cell, cell))
    canvas.alpha_composite(img, (left, bottom - img.height + 1))
    return canvas


def base_sprite() -> Image.Image:
    return place(sprite(17, 26), 32, 7, 28)


def box(img: Image.Image):
    ys, xs = np.nonzero(np.asarray(img)[..., 3])
    return xs.min(), ys.min(), xs.max(), ys.max()


def native_rows() -> dict[str, list[Image.Image]]:
    """sprite-gen's frames the way codex draws them: the base sprite twice as fine, in 64 px cells, swaying one base
    pixel side to side; frame 1 of each row stands one base pixel higher."""
    return {
        r.state: [place(sprite(17, 26, 2), 64, 14 + 2 * (i % 2), 61 - 2 * (i == 1)) for i in range(r.frames)]
        for r in ROWS
    }


def finer(img: Image.Image, w: int, h: int, left: int = 20, bottom: int = 61) -> Image.Image:
    """A native frame drawn finer by a factor that is not whole."""
    return place(img.resize((w, h), Image.Resampling.NEAREST), 64, left, bottom)


def colors(frames: list[Image.Image]) -> set[tuple[int, int, int]]:
    px = np.concatenate([np.asarray(f).reshape(-1, 4) for f in frames])
    return {tuple(int(v) for v in p[:3]) for p in px[px[:, 3] > 0]}


def test_rows_and_tags():
    assert FRAMES == 10
    assert request_states() == {
        "idle": {"frames": 4, "fps": 6, "loop": True, "action": "subtle breathing and blinking"},
        "frontwalk": {"frames": 6, "fps": 10, "loop": True, "action": "creeping walk toward the viewer"},
    }
    # Tools/archive_campaign_art.lua: idle frames 1-4 at 0.18 s, walk 5-10 at 0.1 s (1-based there)
    assert game_json(32, 32, "shadow_walker") == {
        "name": "shadow_walker",
        "image": "shadow_walker.png",
        "frame_width": 32,
        "frame_height": 32,
        "frames": 10,
        "tags": [
            {"name": "idle", "from": 0, "to": 3, "duration": 0.18},
            {"name": "walk", "from": 4, "to": 9, "duration": 0.1},
        ],
    }


def test_shrink_keeps_outlines_and_eyes():
    small = shrink(sprite(17, 26, 2), 17, 26)
    assert np.array_equal(np.asarray(small), np.asarray(sprite(17, 26)))  # an exact 2x drawing comes back exactly
    # 1.5x finer: blocks of one and two pixels; the dark outline and the eyes still show
    fine = sprite(17, 26).resize((26, 39), Image.Resampling.NEAREST)
    back = np.asarray(shrink(fine, 17, 26))
    assert tuple(back[0, 8, :3]) == OUTLINE and tuple(back[25, 8, :3]) == OUTLINE
    assert (back[..., :3] == EYE).all(axis=2).sum() >= 2
    assert set(np.unique(back[..., 3])) <= {0, 255}


def test_fit_frames_size_feet_and_rows():
    frames, report = fit_frames(native_rows(), SPEC, base_sprite())
    assert len(frames) == 10
    assert all(f.size == (32, 32) for f in frames)
    assert all(box(f)[3] == 28 for f in frames)  # frame 1 of each row stood a row higher in the source
    assert all(set(np.unique(np.asarray(f)[..., 3])) <= {0, 255} for f in frames)
    assert report["base_size"] == [17, 26]
    assert report["frame_sizes"] == [[17, 26]] * 10
    assert report["rows"]["idle"] == {"state": "idle", "native_height": 52, "factor": 0.5, "size": [17, 26]}
    assert (report["idle_size"], report["walk_size"], report["idle_height"]) == ([17, 26], [17, 26], 26)
    assert report["size_ok"] is True
    assert report["ground_row"] == 28
    assert report["warnings"] == []
    # the row's middle on the canvas's middle; frames keep their 1-column sway
    lefts = [box(f)[0] for f in frames[:4]]
    assert lefts == [7, 8, 7, 8]


def test_each_row_gets_the_base_height():
    rows = native_rows()
    rows["frontwalk"] = [finer(sprite(17, 26), 22, 34) for _ in range(6)]  # codex drew the walk larger
    _, report = fit_frames(rows, SPEC, base_sprite())
    assert report["rows"]["walk"]["native_height"] == 34
    assert report["rows"]["walk"]["factor"] == pytest.approx(26 / 34, abs=0.001)
    assert report["idle_size"][1] == 26
    assert abs(report["walk_size"][1] - 26) <= 1


def test_rows_drawn_too_tall_for_the_canvas_shrink_instead_of_being_cut():
    rows = native_rows()
    rows["idle"] = [finer(sprite(17, 26), 26, 39) for _ in range(4)]  # 1.5x finer
    rows["idle"][3] = finer(sprite(17, 29), 26, 44)  # reaching up: 26/39 of 44 rows would not fit above row 28
    frames, report = fit_frames(rows, SPEC, base_sprite())
    assert report["rows"]["idle"]["fitted_to_canvas"] is True
    assert report["rows"]["idle"]["factor"] == pytest.approx(29 / 44, abs=0.001)
    assert report["warnings"] == []
    assert box(frames[3])[1] >= 0 and box(frames[3])[3] == 28
    assert report["idle_height"] in (25, 26)  # a little smaller than the base at most: within the tolerance
    assert report["size_ok"] is True


def test_size_differences_are_reported():
    base = base_sprite()
    wide = {r.state: [place(sprite(24, 26, 2), 64, 8, 61) for _ in range(r.frames)] for r in ROWS}
    _, report = fit_frames(wide, SPEC, base)
    assert report["idle_size"] == [24, 26]
    assert report["size_ok"] is False  # 7 cells wider than the base
    tiny = {r.state: [place(sprite(10, 8), 64, 20, 61) for _ in range(r.frames)] for r in ROWS}
    _, report = fit_frames(tiny, SPEC, base)
    assert report["rows"]["idle"]["factor"] == 1.0  # never enlarged
    assert report["size_ok"] is False


def test_heavy_shrinks_warn():
    _, report = fit_frames(native_rows(), SPEC, place(sprite(8, 10), 32, 12, 28))
    assert any("shrunk 0.19x" in w for w in report["warnings"])


def test_frames_take_the_base_sprites_colors():
    rows = native_rows()
    rows["idle"][0] = place(sprite(17, 26, 2, body=(60, 55, 95)), 64, 14, 61)  # a shade codex added
    rows["frontwalk"][2] = place(sprite(17, 26, 2, body=(60, 55, 95)), 64, 14, 61)
    frames, report = fit_frames(rows, SPEC, base_sprite())
    assert colors(frames) <= {BODY, OUTLINE, EYE}
    assert report["colors_used"] == 3
    assert tuple(np.asarray(frames[0])[13, 16, :3]) == tuple(np.asarray(frames[6])[13, 16, :3]) == BODY


def test_a_palette_wins_over_the_base_colors():
    palette = ((0, 0, 0), (50, 50, 80), (255, 255, 160), (200, 0, 0))
    frames, report = fit_frames(native_rows(), PixelSpec(32, 32, 12, palette, ground=3), base_sprite())
    assert colors(frames) == {(0, 0, 0), (50, 50, 80), (255, 255, 160)}
    assert report["colors_used"] == 3


def test_empty_frames_are_errors():
    rows = native_rows()
    rows["idle"][2] = Image.new("RGBA", (64, 64))
    with pytest.raises(ValueError, match="empty idle frame"):
        fit_frames(rows, SPEC, base_sprite())
    with pytest.raises(ValueError, match="no opaque pixels"):
        fit_frames(native_rows(), SPEC, Image.new("RGBA", (32, 32)))


def test_row_sheet_and_gif():
    frames, report = fit_frames(native_rows(), SPEC, base_sprite())
    row = game_row(frames)
    assert row.size == (320, 32)
    assert np.array_equal(np.asarray(row)[:, 64:96], np.asarray(frames[2]))
    sheet = contact_sheet(frames, report["ground_row"], zoom=4)
    assert sheet.width == 10 * (32 * 4 + 4) + 4 and sheet.height > 32 * 4
    gif = Image.open(io.BytesIO(animated_gif(frames, zoom=2)))
    assert (gif.size, gif.n_frames) == ((64, 64), 10)
    durations = []
    for i in range(gif.n_frames):
        gif.seek(i)
        durations.append(gif.info["duration"])
    assert durations == [180] * 4 + [100] * 6
    gif.seek(0)
    rgba = np.asarray(gif.convert("RGBA"))
    assert rgba[0, 0, 3] == 0 and rgba[40, 32, 3] == 255  # transparent around the sprite


def test_load_frames(tmp_path):
    atlas = Image.new("RGBA", (6 * 64, 128))
    layout = {}
    for row, r in enumerate(ROWS):
        layout[r.state] = []
        for i in range(r.frames):
            atlas.paste(place(sprite(17, 26, 2), 64, 15 + i, 60), (i * 64, row * 64))
            layout[r.state].append({"x": i * 64, "y": row * 64, "w": 64, "h": 64})
    atlas.save(tmp_path / "sprite-sheet-alpha.png")
    manifest = {"sprite_sheet_alpha": "sprite-sheet-alpha.png", "frame_layout": {"rows": layout}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    frames = load_frames(tmp_path)
    assert [len(frames[r.state]) for r in ROWS] == [4, 6]
    assert [box(f)[0] for f in frames["frontwalk"]] == [15 + i for i in range(6)]

    layout["frontwalk"] = layout["frontwalk"][:4]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="made 4 frontwalk frames instead of 6"):
        load_frames(tmp_path)


def test_size_tolerance_constant():
    assert animation.SIZE_TOLERANCE == (2, 1)
