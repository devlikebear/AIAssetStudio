import shutil

import numpy as np
import pytest
import soundfile as sf

from aiassetstudio.post.audio import (
    AudioEncodeError,
    detect_tempo,
    encode_ogg,
    leading_quiet_bars,
    load_audio,
    make_loop,
    normalize_peak,
    seam_ratio,
    trim_trailing_silence,
    window_db,
    write_wav,
)

SR = 22050
BPM = 100
BAR_S = 60 / BPM * 4  # 2.4 s


def song(seconds: float = 20.0, silence_s: float = 4.0, quiet_first_bar: bool = True) -> np.ndarray:
    """Stereo: 100 BPM clicks over a 220 Hz tone, then `silence_s` of near silence (a decoder's noise floor)."""
    t = np.arange(round(seconds * SR)) / SR
    y = 0.3 * np.sin(2 * np.pi * 220 * t)
    click = 0.5 * np.hanning(200)
    for i in range(0, len(y) - 200, round(60 / BPM * SR)):
        y[i : i + 200] += click
    if quiet_first_bar:
        y[: round(BAR_S * SR)] *= 0.05  # about 26 dB quieter, like ACE-Step's quiet intros
    y = np.concatenate([y, np.zeros(round(silence_s * SR))])
    y += np.random.default_rng(0).normal(0, 1e-5, len(y))
    return np.stack([y, y], axis=1).astype(np.float32)


def test_window_db():
    db = window_db(np.full((SR, 1), 0.5, np.float32), SR)
    assert len(db) == 20 and np.allclose(db, 20 * np.log10(0.5), atol=0.01)


def test_trim_trailing_silence():
    trimmed = trim_trailing_silence(song(), SR)
    assert abs(len(trimmed) / SR - 20.0) <= 0.05
    loud_to_the_end = song(silence_s=0)
    assert len(trim_trailing_silence(loud_to_the_end, SR)) == len(loud_to_the_end)


def test_quiet_first_bar_detected():
    assert leading_quiet_bars(trim_trailing_silence(song(), SR), SR, BAR_S) == 1
    assert leading_quiet_bars(trim_trailing_silence(song(quiet_first_bar=False), SR), SR, BAR_S) == 0


def test_loop_is_whole_bars_after_the_quiet_intro():
    y = trim_trailing_silence(song(seconds=30), SR)
    loop = make_loop(y, SR, BPM)
    assert abs(len(loop.audio) - loop.bars * BAR_S * SR) <= 1
    assert loop.bars == int((30 - BAR_S - 0.03) // BAR_S)  # 11 bars fit after the quiet bar and the crossfade
    assert loop.start_s == pytest.approx(BAR_S, abs=1 / SR)
    assert loop.end_s == pytest.approx(BAR_S * (1 + loop.bars), abs=1 / SR)
    assert loop.audio.shape[1] == 2


def test_crossfade_removes_the_seam_jump():
    # A tone whose last cycle is cut at three quarters: played on repeat without a crossfade it jumps at the seam.
    loop_s = 8 * BAR_S  # the 8 bars that fit in 20 s
    freq = (round(220 * loop_s) + 0.75) / loop_s
    t = np.arange(round(20 * SR)) / SR
    y = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)[:, None]
    raw = make_loop(y, SR, BPM, crossfade_ms=0)
    faded = make_loop(y, SR, BPM)
    assert raw.bars == faded.bars == 8
    assert raw.seam_ratio > 5
    assert faded.seam_ratio <= 1
    assert seam_ratio(faded.audio) == faded.seam_ratio


def test_too_few_bars():
    with pytest.raises(ValueError, match="whole bars"):
        make_loop(song(seconds=8, silence_s=0, quiet_first_bar=False), SR, BPM)


def test_normalize_peak():
    y = normalize_peak(np.array([[0.1], [-0.25], [0.2]], np.float32))
    assert np.max(np.abs(y)) == pytest.approx(10 ** (-1 / 20), rel=1e-5)
    assert normalize_peak(np.zeros((10, 2), np.float32)).max() == 0


def test_wav_round_trip(tmp_path):
    y = normalize_peak(song(seconds=3, silence_s=0))
    write_wav(tmp_path / "a.wav", y, SR)
    back, sr = load_audio(tmp_path / "a.wav")
    assert sr == SR and back.shape == y.shape
    assert sf.info(str(tmp_path / "a.wav")).subtype == "PCM_16"
    assert np.max(np.abs(back - y)) < 1e-4


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not on PATH")
def test_encode_ogg(tmp_path):
    write_wav(tmp_path / "a.wav", normalize_peak(song(seconds=3, silence_s=0)), SR)
    encode_ogg(tmp_path / "a.wav", tmp_path / "a.ogg")
    info = sf.info(str(tmp_path / "a.ogg"))
    assert info.format == "OGG" and info.duration == pytest.approx(3.0, abs=0.05)
    with pytest.raises(AudioEncodeError, match="ffmpeg failed"):
        encode_ogg(tmp_path / "missing.wav", tmp_path / "b.ogg")


def test_encode_without_ffmpeg(tmp_path):
    with pytest.raises(AudioEncodeError, match="not found"):
        encode_ogg(tmp_path / "a.wav", tmp_path / "a.ogg", ffmpeg=str(tmp_path / "no-ffmpeg.exe"))


def clicks(bpm: float, seconds: float = 40.0) -> np.ndarray:
    """Sharp clicks on every beat over a soft tone: an unmistakable tempo."""
    t = np.arange(round(seconds * SR)) / SR
    y = 0.05 * np.sin(2 * np.pi * 330 * t)
    for start in np.arange(0, seconds - 0.05, 60 / bpm):
        i = round(start * SR)
        y[i : i + 300] += 0.8 * np.exp(-np.arange(300) / 40)
    return y.astype(np.float32)[:, None]


def test_detect_tempo():
    assert detect_tempo(clicks(97.3), SR, 96) == pytest.approx(97.3, abs=0.1)
    assert detect_tempo(clicks(96.0), SR, 96) == pytest.approx(96.0, abs=0.1)
    noise = np.random.default_rng(1).normal(0, 0.2, (round(30 * SR), 1)).astype(np.float32)
    assert detect_tempo(noise, SR, 96) is None  # no steady beat: keep the requested tempo
