import json
import shutil
import subprocess
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from PIL import Image

from aiassetstudio.post.video import (
    FPS,
    Shot,
    assemble,
    clip_frames_used,
    frame_edges,
    sentences,
    shot_filter,
    subtitle_events,
    wrap,
    write_subtitles,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def shot(method="full", clip=Path("c.mp4"), start=0.0, length=10.0, text="말.", head=2.0) -> Shot:
    return Shot(Path("p.png"), clip, 81, method, head, text, start, length)


def test_frames_add_up_however_the_pages_round():
    starts = [0.0, 3.27, 6.54, 9.81, 13.08]
    edges = frame_edges(starts)
    frames = [b - a for a, b in pairwise(edges)]
    assert sum(frames) == round(13.08 * FPS)
    assert edges[3] == round(9.81 * FPS)  # each edge stays on the true time, not on a sum of rounded pages


@pytest.mark.parametrize(
    ("method", "frames", "used"),
    [("full", 160, 81), ("full", 40, 40), ("head", 160, 48), ("head", 20, 20), ("still", 160, 0)],
)
def test_how_much_of_the_clip_shows(method, frames, used):
    assert clip_frames_used(shot(method), frames) == used


def test_a_page_without_a_clip_uses_its_picture():
    source, graph = shot_filter(shot("full", clip=None), 100)
    assert source == Path("p.png")
    assert "zoompan" in graph


def test_a_clip_plays_once_and_never_runs_backwards():
    source, graph = shot_filter(shot("full"), 160)
    assert source == Path("c.mp4")
    assert "reverse" not in graph
    assert "trim=end_frame=81" in graph
    assert "tpad=stop_mode=clone:stop=79" in graph


def test_a_clip_that_fills_the_page_does_not_zoom():
    _, graph = shot_filter(shot("full"), 60)
    assert "zoompan" not in graph
    assert "trim=end_frame=60" in graph


def test_sentences_split_after_their_marks():
    assert sentences('그가 왔다. "누구냐?" 그는 말했다… 끝') == ["그가 왔다.", '"누구냐?"', "그는 말했다…", "끝"]


def test_subtitles_cover_the_narration_exactly_in_order():
    events = subtitle_events(shot(start=5.0, length=9.0, text="가나다. 라마바사아자차카."))
    assert events[0][0] == 5.0
    assert events[-1][1] == pytest.approx(14.0)
    assert events[0][1] == events[1][0]
    assert events[0][1] - events[0][0] < events[1][1] - events[1][0]


def test_wrap_keeps_lines_short():
    wrapped = wrap("가나다 " * 20)
    assert all(len(line) <= 30 for line in wrapped.split(r"\N"))


def test_subtitles_escape_override_braces(tmp_path):
    path = tmp_path / "s.ass"
    write_subtitles(path, [shot(text="글 {\\b1}자.")], ["그림: 모델"], 10.0, 14.0)
    text = path.read_text(encoding="utf-8-sig")
    assert "{" not in text
    assert "Dialogue: 0,0:00:10.00,0:00:14.00,Sub,,0,0,0,,그림: 모델" in text


def tone(seconds: int, rate: int = 24000) -> np.ndarray:
    return (0.1 * np.sin(2 * np.pi * 220 * np.arange(rate * seconds) / rate)).astype(np.float32)


def make_clip(path: Path, frames: int = 32) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=208x156:rate={FPS}"]
        + ["-frames:v", str(frames), "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


def probe(path: Path) -> dict:
    command = ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)]
    return json.loads(subprocess.run(command, capture_output=True, check=True, text=True).stdout)


def frame(path: Path, number: int, out: Path) -> np.ndarray:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            f"select=eq(n\\,{number})",
            "-vframes",
            "1",
            str(out),
        ],
        check=True,
    )
    return np.asarray(Image.open(out).convert("RGB"), dtype=np.int16)


@needs_ffmpeg
def test_a_book_of_three_ways_runs_as_long_as_its_narration(tmp_path):
    clip = tmp_path / "clip.mp4"
    make_clip(clip)
    picture = tmp_path / "picture.png"
    Image.new("RGB", (1184, 880), (120, 90, 60)).save(picture)
    rate = 24000
    sf.write(tmp_path / "audio.wav", tone(8), rate, subtype="PCM_16")
    shots = [
        Shot(picture, clip, 32, "full", 2.0, "첫째 쪽이다. 말이 있다.", 0.0, 2.8),
        Shot(picture, clip, 32, "head", 0.5, "둘째 쪽이다.", 3.0, 1.9),
        Shot(picture, None, 0, "still", 2.0, "셋째 쪽이다.", 5.1, 2.9),
    ]
    out = tmp_path / "book.mp4"
    info = assemble(shots, tmp_path / "audio.wav", out, tmp_path / "work", "ffmpeg", [])

    assert info["page_frames"] == [0, 72, 122]
    assert info["length_s"] == pytest.approx(8.0 + 1.2, abs=1 / FPS)
    streams = {s["codec_type"]: s for s in probe(out)["streams"]}
    assert (streams["video"]["width"], streams["video"]["height"]) == (1280, 960)
    assert int(streams["video"]["nb_read_frames"]) == info["frames"]
    assert streams["video"]["codec_name"] == "h264"
    assert streams["audio"]["codec_name"] == "aac"
    assert float(streams["audio"]["duration"]) == pytest.approx(info["length_s"], abs=0.1)


@needs_ffmpeg
def test_the_held_frame_zooms_slowly_after_the_clip(tmp_path):
    clip = tmp_path / "clip.mp4"
    make_clip(clip, 16)
    picture = tmp_path / "picture.png"
    Image.new("RGB", (100, 100)).save(picture)
    rate = 24000
    sf.write(tmp_path / "audio.wav", tone(3), rate, subtype="PCM_16")
    work = tmp_path / "work"
    assemble(
        [Shot(picture, clip, 16, "full", 2.0, "말.", 0.0, 3.0)],
        tmp_path / "audio.wav",
        tmp_path / "o.mp4",
        work,
        "ffmpeg",
        [],
    )
    segment = work / "seg000.mp4"
    assert int(next(s for s in probe(segment)["streams"])["nb_read_frames"]) == round(4.2 * FPS)
    first_held = frame(segment, 16, tmp_path / "a.png")
    next_held = frame(segment, 17, tmp_path / "b.png")
    last = frame(segment, round(4.2 * FPS) - 1, tmp_path / "c.png")
    assert np.abs(first_held - next_held).mean() < 3  # no jump where the clip stops
    assert np.abs(first_held - last).mean() > np.abs(first_held - next_held).mean() * 3


@needs_ffmpeg
def test_named_models_get_a_last_screen(tmp_path):
    picture = tmp_path / "picture.png"
    Image.new("RGB", (1184, 880), (10, 20, 30)).save(picture)
    rate = 24000
    sf.write(tmp_path / "audio.wav", tone(1), rate, subtype="PCM_16")
    work = tmp_path / "work"
    info = assemble(
        [Shot(picture, None, 0, "still", 2.0, "말.", 0.0, 1.0)],
        tmp_path / "audio.wav",
        tmp_path / "o.mp4",
        work,
        "ffmpeg",
        ["그림: 모델 (라이선스)"],
    )
    assert info["length_s"] == 5.0
    assert "그림: 모델" in (work / "subs.ass").read_text(encoding="utf-8-sig")


def test_a_slower_clip_is_counted_in_its_own_time():
    """A Wan clip has 81 frames at 16 fps: 5 s, so 121 frames of the 24 fps book."""
    wan = Shot(Path("p.png"), Path("c.mp4"), 81, "full", 2.0, "말.", 0.0, 10.0, clip_fps=16)
    assert clip_frames_used(wan, 400) == round(81 / 16 * FPS)
    _, graph = shot_filter(wan, 400)
    assert graph.startswith(f"fps={FPS},trim=end_frame={round(81 / 16 * FPS)}")
