# Spike of 2026-11-01 (docs/plans/notes/studio-spike-2026-11-01.md). Kept as a reference, not run by the app.
"""Lay out the storybook as a PDF: picture above, text below, set by code so Korean text is always correct."""
import os
import json
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(os.environ["SPIKE_BOOK_DIR"])  # holds storyboard.json, pages/, refs/; never commit a work's text
FONT = r"C:\Windows\Fonts\batang.ttc"
PAGE_W, PAGE_H = 1480, 1500
IMG_H = 1100
PAPER = (247, 242, 232)
INK = (45, 44, 42)
MUTED = (120, 112, 100)
REDONE: set[int] = set()  # pages whose second render was chosen


def wrap(draw, text, font, width):
    lines, line = [], ""
    for word in text.split(" "):
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def picture(n):
    name = f"p{n:02d}_s100.png" if n in REDONE else f"p{n:02d}.png"
    return Image.open(ROOT / "pages" / name).convert("RGB").resize((PAGE_W, IMG_H), Image.LANCZOS)


def story_page(page):
    im = Image.new("RGB", (PAGE_W, PAGE_H), PAPER)
    im.paste(picture(page["n"]), (0, 0))
    d = ImageDraw.Draw(im)
    body = ImageFont.truetype(FONT, 38)
    small = ImageFont.truetype(FONT, 24)
    y = IMG_H + 56
    for line in wrap(d, page["text"], body, PAGE_W - 240):
        d.text((120, y), line, font=body, fill=INK)
        y += 66
    d.text((120, PAGE_H - 60), page["chapter"], font=small, fill=MUTED)
    label = str(page["n"])
    d.text((PAGE_W - 120 - d.textlength(label, font=small), PAGE_H - 60), label, font=small, fill=MUTED)
    return im


def cover(title):
    im = Image.new("RGB", (PAGE_W, PAGE_H), PAPER)
    im.paste(picture(4), (0, 0))
    d = ImageDraw.Draw(im)
    big = ImageFont.truetype(FONT, 96)
    small = ImageFont.truetype(FONT, 30)
    d.text((PAGE_W / 2, IMG_H + 150), title, font=big, fill=INK, anchor="mm")
    d.text((PAGE_W / 2, IMG_H + 270), "그림책 시험 제작본", font=small, fill=MUTED, anchor="mm")
    return im


def colophon():
    im = Image.new("RGB", (PAGE_W, PAGE_H), PAPER)
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(FONT, 30)
    lines = book.get("colophon", [])
    y = 620
    for text in lines:
        for line in wrap(d, text, font, PAGE_W - 300):
            d.text((150, y), line, font=font, fill=INK)
            y += 54
        y += 18
    return im


book = json.loads((ROOT / "storyboard.json").read_text(encoding="utf-8"))
t0 = time.monotonic()
pages = [cover(book["title"])] + [story_page(p) for p in book["pages"]] + [colophon()]
out = ROOT / "book.pdf"
pages[0].save(out, save_all=True, append_images=pages[1:], resolution=150, quality=90)
print(out, len(pages), "pages", round(out.stat().st_size / 2**20, 1), "MB", round(time.monotonic() - t0, 1), "s")

rows = [json.loads(line) for line in (ROOT / "render_log.jsonl").read_text(encoding="utf-8").splitlines()]
print("images", len(rows), "render total s", round(sum(r["total_s"] for r in rows), 1),
      "per image avg", round(sum(r["total_s"] for r in rows) / len(rows), 1),
      "min", min(r["total_s"] for r in rows), "max", max(r["total_s"] for r in rows),
      "lowest vram free mb", min(r["vram_free_mb"] for r in rows), "lowest ram free mb", min(r["ram_free_mb"] for r in rows))
for i in (0, 1, 7, 12):
    pages[i].resize((740, 750)).save(ROOT / "pages" / f"_preview_{i}.png")
