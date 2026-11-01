# Spike of 2026-11-01 (docs/plans/notes/studio-spike-2026-11-01.md). Kept as a reference, not run by the app.
"""Build the narrated video: each clip ping-pongs to its page's narration length, then subtitles and audio are added."""
import os
import json
import subprocess
from pathlib import Path

ROOT = Path(os.environ["SPIKE_BOOK_DIR"])  # holds storyboard.json, pages/, refs/; never commit a work's text
TTS = Path(os.environ["SPIKE_TTS_DIR"])
BOOK = json.loads((ROOT / "storyboard.json").read_text(encoding="utf-8"))
DUR = {int(k): v for k, v in json.loads((TTS / "page_durations.json").read_text(encoding="utf-8")).items()}
GAP = 1.2
FPS = 16
# Pages whose clip drifts away from the picture late in the 5 s use only the first 2 s.
DRIFT: set[int] = set()  # filled per book
# Wan can lose a small trait or add a person within 2 s; those pages slowly zoom into the approved picture.
STILLS: dict[int, str] = {}  # page -> approved picture file
WORK = ROOT / "video" / "work"
WORK.mkdir(exist_ok=True)


def run(*args, cwd=None):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True, cwd=cwd)


def stamp(seconds):
    h, m = int(seconds // 3600), int(seconds % 3600 // 60)
    return f"{h}:{m:02d}:{seconds % 60:05.2f}"


def wrap(text, width=30):
    out, line = [], ""
    for word in text.split(" "):
        if len(line) + len(word) + 1 > width and line:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    out.append(line)
    return r"\N".join(out)


events, start = [], 0.0
names = []
for page in BOOK["pages"]:
    n = page["n"]
    length = DUR[n] + GAP
    # Frames counted from the running time, so the rounding of one page never carries into the next.
    frames = round((start + length) * FPS) - round(start * FPS)
    name = f"seg{n:02d}.mp4"
    if n in STILLS:
        graph = (f"[0:v]crop=ih*4/3:ih,scale=2560:1920,zoompan=z='1+0.07*on/{frames}':x='iw/2-(iw/zoom/2)':"
                 f"y='ih/2-(ih/zoom/2)':d={frames}:s=1280x960:fps={FPS},format=yuv420p[out]")
        source = ["-i", str(ROOT / "pages" / STILLS[n])]
    else:
        last = 32 if n in DRIFT else 80
        loop = 2 * (last + 1)
        graph = (f"[0:v]trim=end_frame={last + 1},setpts=PTS-STARTPTS,split[a][b];[b]reverse[r];[a][r]concat=n=2,"
                 f"loop=loop=-1:size={loop}:start=0,setpts=N/{FPS}/TB,"
                 f"scale=1280:960:flags=lanczos,format=yuv420p[out]")
        source = ["-i", str(ROOT / "video" / f"v{n:02d}.mp4")]
    run(*source, "-filter_complex", graph, "-map", "[out]", "-frames:v", str(frames), "-r", str(FPS),
        "-c:v", "libx264", "-crf", "20", "-preset", "fast", str(WORK / name))
    names.append(name)
    events.append(f"Dialogue: 0,{stamp(start)},{stamp(start + DUR[n])},Sub,,0,0,0,,{wrap(page['text'])}")
    start += length

(WORK / "list.txt").write_text("".join(f"file '{n}'\n" for n in names), encoding="utf-8")
(WORK / "subs.ass").write_text(
    "[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 960\n\n[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
    "Style: Sub,Malgun Gothic,38,&H00FFFFFF,&H90000000,&H90000000,3,10,0,2,80,80,44\n\n"
    "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" + "\n".join(events) + "\n",
    encoding="utf-8-sig",
)
run("-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "joined.mp4", cwd=WORK)
out = ROOT / "book_video.mp4"
run("-i", "joined.mp4", "-i", str(TTS / "audiobook_full.mp3"),
    "-vf", f"subtitles=subs.ass,fade=t=in:st=0:d=0.8,fade=t=out:st={start - 1.2:.2f}:d=1.2",
    "-af", f"afade=t=out:st={start - 1.2:.2f}:d=1.2",
    "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-c:a", "aac", "-b:a", "160k", "-shortest",
    "-movflags", "+faststart", str(out), cwd=WORK)
print(out, round(start, 1), "s", round(out.stat().st_size / 2**20, 1), "MB")
