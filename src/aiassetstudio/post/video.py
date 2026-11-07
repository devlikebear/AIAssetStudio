"""A book as a video: each page's clip or approved picture, the narration under them and subtitles on them.

Frame counts come from the running time, so the rounding of one page never carries into the next: rounded page by page,
the 2026-11-01 trial drifted 0.3 s from its narration. A person found clips played back and forth awkward (T3.A.1), so a
clip plays once and its last frame slowly zooms for the rest of the page.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .audio import MP3_LOUDNESS, run_ffmpeg

FPS = 24  # LTX-2.5's own rate; Wan's 16 fps clips are brought up to it
WIDTH, HEIGHT = 1280, 960
ZOOM = 0.07  # how much a page's picture or last frame grows over its time on screen
ZOOM_SIDE = (2560, 1920)  # zoompan rounds to whole pixels; working at twice the size keeps the motion smooth
FADE_IN_S, FADE_OUT_S = 0.8, 1.2
END_CARD_S = 4.0  # the last screen, when the models used must be named
SUBTITLE_FONT = "Malgun Gothic"
SUBTITLE_WIDTH = 30  # characters on a line
SENTENCE = re.compile(r"\S.*?(?:[.!?…][\"”’」』)]*(?=\s|$)|$)", re.DOTALL)

Method = Literal["full", "head", "still"]


@dataclass
class Shot:
    """One page on screen, from `start_s` for `length_s` of narration."""

    picture: Path
    clip: Path | None
    clip_frames: int  # frames in the clip, at clip_fps
    method: Method
    head_s: float  # seconds of the clip that "head" uses
    text: str
    start_s: float
    length_s: float
    clip_fps: float = FPS


def frame_edges(times: list[float], fps: int = FPS) -> list[int]:
    """The frame each time falls on. One page's frames are the difference of two edges, so they add up exactly."""
    return [round(t * fps) for t in times]


def clip_frames_used(shot: Shot, frames: int) -> int:
    """Frames of the clip on screen before its last one holds; 0 for the picture alone."""
    if shot.clip is None or shot.method == "still":
        return 0
    available = round(shot.clip_frames / shot.clip_fps * FPS)
    if shot.method == "head":
        available = min(available, max(1, round(shot.head_s * FPS)))
    return min(available, frames)


def _zoompan(zoom: str, duration: int) -> str:
    w, h = WIDTH, HEIGHT
    position = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    return f"scale={ZOOM_SIDE[0]}:{ZOOM_SIDE[1]},zoompan=z='{zoom}':{position}:d={duration}:s={w}x{h}:fps={FPS}"


def shot_filter(shot: Shot, frames: int) -> tuple[Path, str]:
    """The file a page starts from and the filter that makes its `frames` frames."""
    played = clip_frames_used(shot, frames)
    if not played:
        crop = f"crop=min(iw\\,ih*{WIDTH}/{HEIGHT}):min(ih\\,iw*{HEIGHT}/{WIDTH})"
        return shot.picture, f"{crop},{_zoompan(f'1+{ZOOM}*on/{frames}', frames)},format=yuv420p"
    trim = f"fps={FPS},trim=end_frame={played},setpts=PTS-STARTPTS"
    held = frames - played
    if not held:
        return shot.clip, f"{trim},scale={WIDTH}:{HEIGHT}:flags=lanczos,format=yuv420p"
    zoom = f"if(lt(on,{played}),1,1+{ZOOM}*(on-{played})/{held})"
    return shot.clip, f"{trim},tpad=stop_mode=clone:stop={held},{_zoompan(zoom, 1)},format=yuv420p"


def _stamp(seconds: float) -> str:
    hours, minutes = int(seconds // 3600), int(seconds % 3600 // 60)
    return f"{hours}:{minutes:02d}:{seconds % 60:05.2f}"


def wrap(text: str, width: int = SUBTITLE_WIDTH) -> str:
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    lines.append(line)
    return r"\N".join(lines)


def sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE.findall(text)]


def subtitle_events(shot: Shot) -> list[tuple[float, float, str]]:
    """A page's text, one sentence at a time: a whole page would cover the picture. Each sentence gets a share of the
    narration by its length, which keeps it near the voice; the takes have no word timings."""
    parts = sentences(shot.text)
    total = sum(len(part) for part in parts)
    events, at = [], shot.start_s
    for part in parts:
        length = shot.length_s * len(part) / total
        events.append((at, at + length, part))
        at += length
    return events


def write_subtitles(path: Path, shots: list[Shot], end_card: list[str], end_card_at: float, end_s: float) -> None:
    style = f"Style: Sub,{SUBTITLE_FONT},38,&H00FFFFFF,&H90000000,&H90000000,3,10,0,2,80,80,44"
    head = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {WIDTH}\nPlayResY: {HEIGHT}\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, BorderStyle, Outline, Shadow, "
        f"Alignment, MarginL, MarginR, MarginV\n{style}\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = [event for shot in shots for event in subtitle_events(shot)]
    if end_card:
        events.append((end_card_at, end_s, "\n".join(end_card)))
    lines = []
    for start, end, text in events:
        body = r"\N".join(wrap(line) for line in text.replace("{", "(").replace("}", ")").split("\n"))
        lines.append(f"Dialogue: 0,{_stamp(start)},{_stamp(end)},Sub,,0,0,0,,{body}")
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8-sig")


def assemble(shots: list[Shot], audio: Path, out: Path, work: Path, ffmpeg: str, end_card: list[str]) -> dict:
    """`audio` holds every page at its `start_s`. Returns the video's length and each page's first frame."""
    work.mkdir(parents=True, exist_ok=True)
    spoken_end = shots[-1].start_s + shots[-1].length_s
    total = spoken_end + (END_CARD_S if end_card else FADE_OUT_S)
    edges = frame_edges([*(s.start_s for s in shots), total])
    names = []
    for i, shot in enumerate(shots):
        frames = edges[i + 1] - edges[i]
        source, graph = shot_filter(shot, frames)
        name = f"seg{i:03d}.mp4"
        run_ffmpeg(
            ffmpeg,
            ["-i", str(source), "-vf", graph, "-frames:v", str(frames), "-r", str(FPS), "-fps_mode", "cfr"]
            + ["-c:v", "libx264", "-crf", "20", "-preset", "fast", "-an", str(work / name)],
        )
        names.append(name)
    (work / "list.txt").write_text("".join(f"file '{name}'\n" for name in names), encoding="utf-8")
    write_subtitles(work / "subs.ass", shots, end_card, spoken_end, total)
    run_ffmpeg(ffmpeg, ["-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "joined.mp4"], cwd=work)
    length = edges[-1] / FPS
    fades = f"fade=t=in:st=0:d={FADE_IN_S},fade=t=out:st={length - FADE_OUT_S:.3f}:d={FADE_OUT_S}"
    run_ffmpeg(
        ffmpeg,
        ["-i", "joined.mp4", "-i", str(audio.resolve()), "-vf", f"subtitles=subs.ass,{fades}"]
        + ["-af", f"{MP3_LOUDNESS},apad=whole_dur={length:.3f}", "-t", f"{length:.3f}"]
        + ["-c:v", "libx264", "-crf", "20", "-preset", "medium", "-fps_mode", "cfr"]
        + ["-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out.resolve())],
        cwd=work,
    )
    return {"length_s": round(length, 3), "fps": FPS, "page_frames": edges[:-1], "frames": edges[-1]}
