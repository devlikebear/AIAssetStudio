"""Animation trial (T1.A.1): does codex keep the base sprite's size, and does a 6-frame walk hold up?

Makes idle (4 frames) + frontwalk (6 frames) rows of one studio sprite with sprite-gen's codex provider, in four
variants:
  a  the asset's description as it is
  b  the description plus the base sprite's size in pixels
  c  a's rows extracted again without sprite-gen's height cap (a 64 px cell, <out>/native), then all 10 frames
     shrunk by one factor so the idle height matches the base, and put back on the 32x32 feet row
  d  like c, but each row shrunk by its own factor so both rows match the base height
c and d make no new codex call. A variant whose run is complete is not run again (--force redoes it).
It reads the studio's data folder (read only) and writes only to --out (a temp folder by default):
<out>/<variant>/ is the sprite-gen run, <out>/trial.json the numbers, <out>/sheet.png the frames at 8x with the
feet row, <out>/<variant>.gif the 10 frames in game timing (idle 0.18 s, walk 0.1 s).

Variants a and b send to OpenAI through the Codex CLI (ChatGPT subscription): the sprite enlarged to 1024x1024,
sprite-gen's layout guides and prompts. c sends nothing.

    uv run python scripts/animation_trial.py [--asset 622203551b15] [--out DIR] [--variants a,b,c,d] [--force]
"""

import argparse
import json
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from aiassetstudio.config import find_codex_dir, load_settings

STATES = {
    "idle": {"frames": 4, "fps": 5, "loop": True, "action": "subtle breathing and blinking"},
    "frontwalk": {"frames": 6, "fps": 10, "loop": True, "action": "creeping walk toward the viewer"},
}
SIZE_HINT = (
    "The character is exactly {w} pixels wide and {h} pixels tall on the {cw}x{ch} grid, the same size as the base "
    "image; keep that size in every frame."
)
CELL = 32
MARGIN = 3  # LAST LIGHT's feet row: 32 - 3 - 1 = 28
PALETTE = 12
UNCAPPED_CELL = 64  # big enough that sprite-gen's cap (cell - margin) never shrinks a row
ZOOM = 8
GAME_MS = [180] * 4 + [100] * 6
OPAQUE = 128


def load_asset(data_dir: Path, asset_id: str) -> tuple[Image.Image, str]:
    db = sqlite3.connect(f"file:{data_dir / 'studio.db'}?mode=ro", uri=True)
    row = db.execute("select files, meta from assets where id = ?", (asset_id,)).fetchone()
    db.close()
    if row is None:
        sys.exit(f"no asset {asset_id} in {data_dir}")
    files, meta = json.loads(row[0]), json.loads(row[1])
    with Image.open(data_dir / files["processed"]) as img:
        return img.convert("RGBA"), meta.get("description", "")


def opaque_box(img: Image.Image) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom), right and bottom inclusive."""
    a = np.asarray(img.convert("RGBA"))[..., 3] >= OPAQUE
    ys, xs = np.nonzero(a)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(ys) else None


def size_of(img: Image.Image) -> tuple[int, int] | None:
    box = opaque_box(img)
    return (box[2] - box[0] + 1, box[3] - box[1] + 1) if box else None


def sprite_gen(exe: str, tool: str, *args: str, codex_dir: Path | None = None) -> dict:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if codex_dir is not None:
        env["PATH"] = f"{codex_dir}{os.pathsep}{env.get('PATH', '')}"
    started = time.monotonic()
    done = subprocess.run([exe, tool, *args], capture_output=True, text=True, encoding="utf-8", env=env, check=False)
    seconds = round(time.monotonic() - started, 1)
    out = done.stdout.strip()
    try:  # every stage but gen-set prints one JSON object last
        result = json.loads(out[out.rindex("\n{") + 1 :] if "\n{" in out else out)
    except ValueError:
        result = {"output": out[-2000:]}
    result["_seconds"] = seconds
    result["_exit"] = done.returncode
    if done.returncode != 0:
        print(f"  {tool} exited {done.returncode}: {out[-1500:]}\n{done.stderr[-1500:]}", file=sys.stderr)
    return result


def prepare(exe: str, run: Path, base: Path, description: str, cell: int) -> dict:
    run.mkdir(parents=True, exist_ok=True)
    request = run.parent / f"{run.name}-request.json"
    request.write_text(json.dumps({"states": STATES}), encoding="utf-8")
    return sprite_gen(
        exe, "prepare", "--out-dir", str(run), "--character-id", "trial-sprite", "--base-image", str(base),
        "--description", description, "--cell-size", str(cell), "--safe-margin", str(MARGIN),
        "--fit-pixel-unfake", "--fit-palette-size", str(PALETTE), "--fit-align-x", "foot-centroid",
        "--fit-align-y", "bottom", "--fit-ground-frames", "--request", str(request), "--force",
    )  # fmt: skip


def run_frames(run: Path) -> dict[str, list[Image.Image]]:
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    atlas = Image.open(run / manifest["sprite_sheet_alpha"]).convert("RGBA")
    rows = manifest["frame_layout"]["rows"]
    return {s: [atlas.crop((r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"])) for r in rows[s]] for s in STATES}


def extract_warnings(run: Path) -> list[str]:
    path = run / "frames" / "frames-manifest.json"
    return json.loads(path.read_text(encoding="utf-8")).get("warnings", []) if path.exists() else []


def dominant(opaque: np.ndarray) -> np.ndarray:
    """sprite-gen's kCentroid block color: 2-means from the darkest and lightest pixel, the bigger cluster wins,
    but a dark cluster of 40% or more far darker than the other wins too (eyes and outlines survive). Returns the
    cluster's most common color instead of its mean, so no new colors appear and the palette holds."""
    px = opaque.astype(np.int64)
    luma = px @ np.array([299, 587, 114])
    centroids = np.stack([px[luma.argmin()], px[luma.argmax()]])
    for _ in range(3):
        d = ((px[:, None, :] - centroids[None]) ** 2).sum(axis=2)
        assign = (d[:, 1] < d[:, 0]).astype(int)
        for k in (0, 1):
            if (assign == k).any():
                centroids[k] = px[assign == k].sum(axis=0) // (assign == k).sum()
    counts = np.bincount(assign, minlength=2)
    pick = 0 if counts[0] >= counts[1] else 1
    c_luma = centroids @ np.array([299, 587, 114])
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


def kcentroid(img: Image.Image, width: int, height: int) -> Image.Image:
    src = np.asarray(img.convert("RGBA"))
    sh, sw = src.shape[:2]
    out = np.zeros((height, width, 4), np.uint8)
    for oy in range(height):
        y0 = oy * sh // height
        y1 = max(y0 + 1, (oy + 1) * sh // height)
        for ox in range(width):
            x0 = ox * sw // width
            x1 = max(x0 + 1, (ox + 1) * sw // width)
            block = src[y0:y1, x0:x1].reshape(-1, 4)
            opaque = block[block[:, 3] >= OPAQUE][:, :3]
            if len(opaque) * 2 < len(block):
                continue
            out[oy, ox, :3] = opaque[0] if len(opaque) == 1 else dominant(opaque)
            out[oy, ox, 3] = 255
    return Image.fromarray(out)


def shrink_to_base(
    frames: dict[str, list[Image.Image]], base_h: int, per_row: bool
) -> tuple[dict[str, list[Image.Image]], dict[str, float]]:
    """Shrink uncapped frames so the idle row's median height (per_row: each row's) is the base height. The whole
    cell shrinks, so frames keep their places in the row; each row is centered on its own middle and each frame
    stands on the 32x32 feet row."""
    heights = {s: statistics.median(size_of(f)[1] for f in fs) for s, fs in frames.items()}
    factors = {s: min(1.0, base_h / heights[s if per_row else "idle"]) for s in frames}
    feet = CELL - MARGIN - 1
    placed = {}
    for s, fs in frames.items():
        side = round(UNCAPPED_CELL * factors[s])
        shrunk = [kcentroid(f, side, side) for f in fs]
        boxes = [opaque_box(f) for f in shrunk]
        mid = (min(b[0] for b in boxes) + max(b[2] for b in boxes) + 1) / 2
        placed[s] = []
        for f in shrunk:
            cell = Image.new("RGBA", (CELL, CELL))
            cell.paste(f, (round(CELL / 2 - mid), feet - opaque_box(f)[3]), f)  # paste clips what spills over
            placed[s].append(cell)
    return placed, factors


def colors_used(frames: dict[str, list[Image.Image]]) -> int:
    px = np.concatenate([np.asarray(f.convert("RGBA")).reshape(-1, 4) for fs in frames.values() for f in fs])
    return len(np.unique(px[px[:, 3] >= OPAQUE][:, :3], axis=0))


def row_report(frames: list[Image.Image]) -> list[dict]:
    out = []
    for f in frames:
        box = opaque_box(f)
        out.append({"size": list(size_of(f)), "feet_row": box[3]} if box else {"size": None})
    return out


def tile(img: Image.Image) -> Image.Image:
    t = CELL * ZOOM
    bg = Image.new("RGBA", (t, t), (205, 205, 205, 255))
    d = ImageDraw.Draw(bg)
    for y in range(0, t, 2 * ZOOM):
        for x in range(0, t, 2 * ZOOM):
            if (x // (2 * ZOOM) + y // (2 * ZOOM)) % 2:
                d.rectangle([x, y, x + 2 * ZOOM - 1, y + 2 * ZOOM - 1], fill=(175, 175, 175, 255))
    bg.alpha_composite(img.resize((CELL * ZOOM, CELL * ZOOM), Image.Resampling.NEAREST))
    y = (CELL - MARGIN) * ZOOM  # the line under the feet row
    d.line([(0, y), (t, y)], fill=(220, 60, 60, 255))
    return bg


def sheet(base: Image.Image, results: dict[str, dict[str, list[Image.Image]]], out: Path) -> None:
    font = ImageFont.truetype("malgun.ttf", 16)
    small = ImageFont.truetype("malgun.ttf", 13)
    t, gap = CELL * ZOOM, 10
    width = 90 + 11 * (t + gap)
    height = 40 + len(results) * (t + 60)
    img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text(
        (12, 10), "왼쪽은 기본 그림, 이어서 대기 4 + 이동 6 · 8배 · 빨간 선은 발 줄(28) 아래", fill=(0, 0, 0), font=font
    )
    y = 40
    for variant, frames in results.items():
        d.text((12, y + t // 2 - 10), variant, fill=(0, 0, 0), font=font)
        cells = [base] + frames["idle"] + frames["frontwalk"]
        for i, f in enumerate(cells):
            x = 90 + i * (t + gap)
            img.paste(tile(f), (x, y))
            box = opaque_box(f)
            label = ("base " if i == 0 else f"#{i - 1} ") + (
                f"{box[2] - box[0] + 1}x{box[3] - box[1] + 1} feet {box[3]}" if box else "empty"
            )
            d.text((x, y + t + 4), label, fill=(70, 70, 70), font=small)
        y += t + 60
    img.save(out)


def gif(frames: dict[str, list[Image.Image]], out: Path) -> None:
    tiles = [tile(f).convert("P", palette=Image.Palette.ADAPTIVE) for f in frames["idle"] + frames["frontwalk"]]
    tiles[0].save(out, save_all=True, append_images=tiles[1:], duration=GAME_MS, loop=0)


def generate(args, run: Path, base: Path, description: str, codex_dir: Path | None) -> dict:
    entry: dict = {"description": description, "prepare": prepare(args.sprite_gen, run, base, description, CELL)}
    genset = sprite_gen(args.sprite_gen, "gen-set", "--run-dir", str(run), "--provider", "codex", "--concurrency", "2", codex_dir=codex_dir)  # fmt: skip
    set_report = run / "reports" / "gen-set" / "set.report.json"
    items = json.loads(set_report.read_text(encoding="utf-8"))["items"] if set_report.exists() else []
    rows = {i["state"]: {k: i.get(k) for k in ("ok", "elapsed_seconds", "error")} for i in items}
    entry["generate"] = {"seconds": genset["_seconds"], "rows": rows}
    return entry | finish(args, run)


def finish(args, run: Path) -> dict:
    return {
        "extract": sprite_gen(args.sprite_gen, "extract", "--run-dir", str(run)),
        "compose": sprite_gen(args.sprite_gen, "compose-atlas", "--run-dir", str(run)),
        "inspect": sprite_gen(args.sprite_gen, "inspect", "--run-dir", str(run)),
        "warnings": extract_warnings(run),
    }


def main() -> None:
    settings = load_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--asset", default="622203551b15")
    parser.add_argument("--data", type=Path, default=settings.data_dir, help="the studio's data folder (read only)")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(tempfile.gettempdir()) / "aias-animation-trial" / time.strftime("%Y%m%d-%H%M%S"),
    )
    parser.add_argument("--variants", default="a,b,c,d")
    parser.add_argument("--force", action="store_true", help="run variants again even if their runs are complete")
    parser.add_argument("--sprite-gen", default=settings.sprite_gen)
    args = parser.parse_args()
    variants = set(args.variants.split(","))
    if unknown := variants - set("abcd"):
        sys.exit(f"unknown variants {sorted(unknown)}")
    if variants & {"c", "d"}:
        variants.add("a")  # c and d reuse a's rows
    codex_dir = find_codex_dir(settings)
    sprite, description = load_asset(args.data, args.asset)
    w, h = size_of(sprite)
    args.out.mkdir(parents=True, exist_ok=True)
    base = args.out / "base.png"
    sprite.resize((sprite.width * 32, sprite.height * 32), Image.Resampling.NEAREST).save(base)
    print(f"asset {args.asset}: {w}x{h} pixels, {description!r}; out {args.out}; codex from {codex_dir or 'PATH'}")
    trial_json = args.out / "trial.json"
    previous = json.loads(trial_json.read_text(encoding="utf-8"))["variants"] if trial_json.exists() else {}
    report = {"asset": args.asset, "base_size": [w, h], "description": description, "variants": previous}
    descriptions = {"a": description, "b": f"{description}. {SIZE_HINT.format(w=w, h=h, cw=CELL, ch=CELL)}"}
    results: dict[str, dict[str, list[Image.Image]]] = {}
    for variant in sorted(variants):
        run = args.out / (variant if variant in descriptions else "native")
        entry = dict(previous.get(variant, {}))
        if args.force or not (run / "manifest.json").exists():
            if variant in descriptions:
                print(f"{variant}: sends to OpenAI (Codex CLI): base.png (1024x1024), layout guides and prompts")
                entry = generate(args, run, base, descriptions[variant], codex_dir)
            else:
                entry = {"prepare": prepare(args.sprite_gen, run, base, description, UNCAPPED_CELL)}
                shutil.copytree(args.out / "a" / "raw", run / "raw", dirs_exist_ok=True)
                entry |= finish(args, run)
        if not (run / "manifest.json").exists():
            report["variants"][variant] = entry
            print(f"{variant}: no frames")
            continue
        frames = run_frames(run)
        if variant in ("c", "d"):
            entry["native"] = {s: row_report(fs) for s, fs in frames.items()}
            frames, entry["factors"] = shrink_to_base(frames, h, per_row=variant == "d")
        entry["rows"] = {s: row_report(fs) for s, fs in frames.items()}
        entry["heights"] = {s: statistics.median(size_of(f)[1] for f in fs) for s, fs in frames.items()}
        entry["height_diff"] = {s: v - h for s, v in entry["heights"].items()}
        entry["colors_used"] = colors_used(frames)
        results[variant] = frames
        report["variants"][variant] = entry
        gif(frames, args.out / f"{variant}.gif")
        sizes = {s: [r["size"] for r in rs] for s, rs in entry["rows"].items()}
        print(f"{variant}: median heights {entry['heights']} (base {h}), {entry['colors_used']} colors, sizes {sizes}")
    trial_json.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if results:
        sheet(sprite, {v: results[v] for v in sorted(results)}, args.out / "sheet.png")
    print(trial_json)


if __name__ == "__main__":
    main()
