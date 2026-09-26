"""A stand-in for the sprite-gen CLI in tests: the same stages, files and JSON, and no network.

    python tests/fake_spritegen.py <prepare|gen-set|extract|compose-atlas|inspect> [options]

- prepare writes sprite-request.json (cell, states) and base-source.png.
- gen-set "generates" each state row by copying the base image to raw/<state>.png, and writes
  reports/gen-set/set.report.json.
- extract turns raw/<state>.png into frames the way codex draws them: the subject FAKE_SPRITEGEN_HEIGHTS tall
  (default idle=34, frontwalk=38 cells, larger than the base), one column further right on odd frames, feet on the
  cell's feet row. A subject taller than the cap (cell - margin) is shrunk to it, with sprite-gen's warning.
- compose-atlas writes sprite-sheet-alpha.png and manifest.json (frame_layout.rows[state] = x, y, w, h).
- inspect reports ok.

Environment:
  FAKE_SPRITEGEN_LOG     append {"tool", "args", "path", "pid"} per call to this file (JSON lines)
  FAKE_SPRITEGEN_FAIL    a stage name: that stage fails (gen-set: every row, the way codex fails without a login)
  FAKE_SPRITEGEN_SLOW    "<stage>:<seconds>": sleep that long in that stage first
  FAKE_SPRITEGEN_HEIGHTS "idle=34,frontwalk=38": subject height per state in extract
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from PIL import Image


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def fail(tool: str) -> None:
    emit({"ok": False, "errors": [f"fake {tool} failure"], "warnings": []})
    sys.exit(1)


def load_request(run: Path) -> dict:
    return json.loads((run / "sprite-request.json").read_text(encoding="utf-8"))


def prepare(args, extra) -> None:
    run = Path(args.out_dir)
    run.mkdir(parents=True, exist_ok=True)
    states = json.loads(Path(args.request).read_text(encoding="utf-8"))["states"]
    margin = args.safe_margin if args.safe_margin is not None else int(args.cell_height * 0.094)  # sprite-gen's default
    cell = {"width": args.cell_width, "height": args.cell_height, "safe_margin": margin}
    request = {"cell": cell, "states": states, "character": {"description": args.description}, "flags": extra}
    (run / "sprite-request.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    shutil.copyfile(args.base_image, run / "base-source.png")
    emit({"ok": True, "run_dir": str(run), "states": list(states)})


def gen_set(args, extra) -> None:
    run = Path(args.run_dir)
    states = list(load_request(run)["states"])
    failing = os.environ.get("FAKE_SPRITEGEN_FAIL") == "gen-set"
    items = []
    for state in states:
        if failing:
            items.append({"state": state, "ok": False, "error": "gen exited 1; codex: not logged in"})
            continue
        (run / "raw").mkdir(exist_ok=True)
        shutil.copyfile(run / "base-source.png", run / "raw" / f"{state}.png")
        items.append({"state": state, "ok": True, "provider": args.provider, "elapsed_seconds": 0.1})
    for item in items:
        print(json.dumps({"state": item["state"], "ok": item["ok"]}))
    report = {
        "kind": "sprite-gen-gen-set-report",
        "states": states,
        "ok": sum(1 for i in items if i["ok"]),
        "failed": [i["state"] for i in items if not i["ok"]],
        "not_started": [],
        "items": items,
    }
    (run / "reports" / "gen-set").mkdir(parents=True, exist_ok=True)
    (run / "reports" / "gen-set" / "set.report.json").write_text(json.dumps(report), encoding="utf-8")
    print("| state | provider | resolved from | seconds | status |\n|---|---|---|---|---|")
    sys.exit(1 if failing else 0)


def heights() -> dict[str, int]:
    spec = os.environ.get("FAKE_SPRITEGEN_HEIGHTS", "idle=34,frontwalk=38")
    return {k: int(v) for k, v in (pair.split("=") for pair in spec.split(","))}


def extract(args, extra) -> None:
    run = Path(args.run_dir)
    request = load_request(run)
    cell_w, cell_h, margin = request["cell"]["width"], request["cell"]["height"], request["cell"]["safe_margin"]
    tall = heights()
    rows, warnings = [], []
    for state, cfg in request["states"].items():
        raw = run / "raw" / f"{state}.png"
        if not raw.is_file():
            emit({"ok": False, "errors": [f"{state}: missing raw row {raw}"], "warnings": []})
            sys.exit(1)
        subject = Image.open(raw).convert("RGBA")
        subject = subject.crop(subject.getbbox())
        height = tall.get(state, 34)
        width = max(1, round(subject.width * height / subject.height))
        cap = cell_h - margin
        if height > cap:
            warnings.append(f"{state}: native logical exceeds the physical cap {cell_w}x{cap} — capped frames")
            width, height = max(1, round(width * cap / height)), cap
        drawn = subject.resize((width, height), Image.Resampling.NEAREST)
        (run / "frames" / state).mkdir(parents=True, exist_ok=True)
        files = []
        for i in range(int(cfg["frames"])):
            frame = Image.new("RGBA", (cell_w, cell_h))
            frame.alpha_composite(drawn, ((cell_w - width) // 2 + i % 2, cell_h - margin - height))
            name = f"frames/{state}/frame-{i}.png"
            frame.save(run / name)
            files.append(name)
        rows.append({"state": state, "frames": len(files), "files": files, "ok": True})
    manifest = {"ok": True, "engine": "component-row", "engine_revision": "fake", "rows": rows}
    manifest |= {"warnings": warnings, "errors": []}
    (run / "frames" / "frames-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    emit({k: v for k, v in manifest.items() if k != "rows"})


def compose(args, extra) -> None:
    run = Path(args.run_dir)
    request = load_request(run)
    cell_w, cell_h = request["cell"]["width"], request["cell"]["height"]
    states = request["states"]
    columns = max(int(cfg["frames"]) for cfg in states.values())
    atlas = Image.new("RGBA", (columns * cell_w, len(states) * cell_h))
    layout = {}
    for row, (state, cfg) in enumerate(states.items()):
        layout[state] = []
        for i in range(int(cfg["frames"])):
            x, y = i * cell_w, row * cell_h
            atlas.alpha_composite(Image.open(run / "frames" / state / f"frame-{i}.png").convert("RGBA"), (x, y))
            layout[state].append({"x": x, "y": y, "w": cell_w, "h": cell_h})
    atlas.save(run / "sprite-sheet-alpha.png")
    manifest = {
        "sprite_sheet_alpha": "sprite-sheet-alpha.png",
        "frame_layout": {"cellWidth": cell_w, "cellHeight": cell_h, "columns": columns, "rows": layout},
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    emit({"ok": True, "atlas": str(run / "sprite-sheet-alpha.png"), "manifest": str(run / "manifest.json")})


def inspect(args, extra) -> None:
    emit({"ok": True, "warnings": ["fake inspect: nothing checked"], "errors": []})


def main() -> None:
    tool, rest = sys.argv[1], sys.argv[2:]
    if log := os.environ.get("FAKE_SPRITEGEN_LOG"):
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"tool": tool, "args": rest, "path": os.environ.get("PATH", ""), "pid": os.getpid()}))
            f.write("\n")
    slow_tool, _, seconds = os.environ.get("FAKE_SPRITEGEN_SLOW", "").partition(":")
    if slow_tool == tool:
        time.sleep(float(seconds))
    if os.environ.get("FAKE_SPRITEGEN_FAIL") == tool and tool != "gen-set":
        fail(tool)
    parser = argparse.ArgumentParser()
    for name in ("--out-dir", "--run-dir", "--character-id", "--base-image", "--description", "--request"):
        parser.add_argument(name)
    for name in ("--cell-width", "--cell-height", "--safe-margin", "--concurrency"):
        parser.add_argument(name, type=int)
    parser.add_argument("--provider")
    args, extra = parser.parse_known_args(rest)
    tools = {"prepare": prepare, "gen-set": gen_set, "extract": extract, "compose-atlas": compose, "inspect": inspect}
    tools[tool](args, extra)


if __name__ == "__main__":
    main()
