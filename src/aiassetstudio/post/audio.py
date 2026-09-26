"""Post-processing for generated music: trailing silence, quiet intro, a bar-aligned loop, peak level, WAV and OGG.

ACE-Step songs end early: all four 90 s test songs (2026-09-24) ended with 3-6 s or more of silence. A battle theme
with only "[Instrumental]" as lyrics started with about 4 s at around -24 dB; with section tags it did not.
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

WINDOW_S = 0.05
# Windows this far below the song's loud level (90th percentile of window levels) count as silence. The plan measured
# against the median, but a long quiet intro drags the median down: the "[Instrumental]" battle test song (median
# -26.5 dB, 8 bars near -40 dB) kept its -65 dB tail, 1.5 dB short of the median-based cut.
SILENCE_REL_DB = -40.0
SILENCE_REFERENCE_PERCENTILE = 90
QUIET_INTRO_REL_DB = -12.0  # bars this far below the median at the start are skipped by the loop
MAX_QUIET_BARS = 4
CROSSFADE_MS = 30.0
MIN_LOOP_BARS = 4
TEMPO_MAX_ERROR_S = 0.020  # beats this close (rms) to a straight line mean the tempo can be trusted
MIN_TEMPO_BEATS = 16
PEAK_DBFS = -1.0
OGG_QUALITY = 6


class AudioEncodeError(RuntimeError):
    """ffmpeg could not make the OGG; the message carries its error output."""


@dataclass
class LoopResult:
    audio: np.ndarray  # (frames, channels)
    start_s: float  # where the loop starts in the trimmed song
    end_s: float
    bars: int
    seam_ratio: float


def load_audio(path: str | Path) -> tuple[np.ndarray, int]:
    """Samples as float32 (frames, channels), and the sample rate."""
    y, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return y, sr


def _mono(y: np.ndarray) -> np.ndarray:
    return y.mean(axis=1) if y.ndim == 2 else y


def _db(rms: np.ndarray | float) -> np.ndarray:
    return 20 * np.log10(np.maximum(rms, 1e-10))


def window_db(y: np.ndarray, sr: int, win_s: float = WINDOW_S) -> np.ndarray:
    """RMS level in dB of consecutive `win_s` windows (a partial last window is left out)."""
    mono = _mono(y).astype(np.float64)
    win = max(1, round(win_s * sr))
    n = len(mono) // win
    if n == 0:
        return _db(np.sqrt(np.mean(mono**2))) * np.ones(1) if len(mono) else np.zeros(0)
    return _db(np.sqrt(np.mean(mono[: n * win].reshape(n, win) ** 2, axis=1)))


def trim_trailing_silence(
    y: np.ndarray, sr: int, rel_db: float = SILENCE_REL_DB, win_s: float = WINDOW_S
) -> np.ndarray:
    """Cut the windows at the end that are all `rel_db` or more below the song's loud level."""
    db = window_db(y, sr, win_s)
    if len(db) == 0:
        return y
    audible = np.nonzero(db > np.percentile(db, SILENCE_REFERENCE_PERCENTILE) + rel_db)[0]
    if len(audible) == 0 or audible[-1] == len(db) - 1:
        return y
    return y[: (audible[-1] + 1) * max(1, round(win_s * sr))]


def leading_quiet_bars(
    y: np.ndarray, sr: int, bar_s: float, rel_db: float = QUIET_INTRO_REL_DB, max_bars: int = MAX_QUIET_BARS
) -> int:
    """How many whole bars from the start are `rel_db` or more below the song's median window level (at most
    `max_bars`)."""
    median = np.median(window_db(y, sr))
    mono = _mono(y).astype(np.float64)
    bar = round(bar_s * sr)
    count = 0
    while count < max_bars and (count + 1) * bar <= len(mono):
        segment = mono[count * bar : (count + 1) * bar]
        if _db(np.sqrt(np.mean(segment**2))) >= median + rel_db:
            break
        count += 1
    return count


def detect_tempo(y: np.ndarray, sr: int, requested_bpm: float, max_error_s: float = TEMPO_MAX_ERROR_S) -> float | None:
    """The song's actual tempo when its beats are steady enough to trust, else None (use the requested tempo).

    ACE-Step does not always keep the requested tempo: a 96 BPM village theme came out at 98.01 BPM (2026-09-25), so
    32 bars of 96 BPM ended the loop about 2.6 beats off the bar. Beats are tracked near the requested tempo and fitted
    with a straight line; the fit is used only when the beats lie within `max_error_s` (rms) of it and the tempo is
    within 10% of the request (half and double time are folded back).
    """
    import librosa  # heavy (numba); only BGM jobs need it

    _, beats = librosa.beat.beat_track(y=_mono(y), sr=sr, start_bpm=requested_bpm, units="time", tightness=400)
    if len(beats) < MIN_TEMPO_BEATS:
        return None
    index = np.arange(len(beats))
    slope, intercept = np.polyfit(index, beats, 1)
    if np.sqrt(np.mean((beats - (slope * index + intercept)) ** 2)) > max_error_s:
        return None
    bpm = 60.0 / slope
    bpm *= min((0.5, 1.0, 2.0), key=lambda f: abs(bpm * f - requested_bpm))
    return float(bpm) if abs(bpm / requested_bpm - 1) <= 0.1 else None


def seam_ratio(loop: np.ndarray) -> float:
    """The jump from the loop's last sample back to its first, relative to the 99th percentile of the sample-to-sample
    changes inside it. At most 1: the seam changes no more than an ordinary step of the song."""
    loop = loop if loop.ndim == 2 else loop[:, None]
    jump = float(np.max(np.abs(loop[0].astype(np.float64) - loop[-1])))
    typical = float(np.percentile(np.abs(np.diff(loop.astype(np.float64), axis=0)), 99))
    return jump / typical if typical > 0 else (0.0 if jump == 0 else float("inf"))


def make_loop(
    y: np.ndarray,
    sr: int,
    bpm: float,
    beats_per_bar: int = 4,
    crossfade_ms: float = CROSSFADE_MS,
    min_bars: int = MIN_LOOP_BARS,
) -> LoopResult:
    """The longest run of whole bars after the quiet intro, made to loop without a click.

    The first `crossfade_ms` of the loop are blended with the audio right after its end, so on repeat the sample
    that follows the loop's last sample is (nearly) the one that followed it in the song. This removes the click;
    it does not make the music itself flow naturally from end to start. Raises ValueError below `min_bars` bars.
    """
    y = y if y.ndim == 2 else y[:, None]
    bar_s = 60.0 / bpm * beats_per_bar
    start = round(leading_quiet_bars(y, sr, bar_s) * bar_s * sr)
    fade = round(crossfade_ms / 1000 * sr)
    bars = int((len(y) - start - fade) // (bar_s * sr))
    if bars < min_bars:
        raise ValueError(f"only {max(bars, 0)} whole bars of {bar_s:.2f} s after the intro; a loop needs {min_bars}")
    length = round(bars * bar_s * sr)
    loop = y[start : start + length].astype(np.float32, copy=True)
    if fade:
        ramp = np.linspace(0.0, 1.0, fade, endpoint=False, dtype=np.float32)[:, None]
        tail = y[start + length : start + length + fade]
        loop[:fade] = loop[:fade] * ramp + tail * (1 - ramp)
    return LoopResult(loop, start / sr, (start + length) / sr, bars, seam_ratio(loop))


def normalize_peak(y: np.ndarray, peak_dbfs: float = PEAK_DBFS) -> np.ndarray:
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak == 0:
        return y
    return (y * (10 ** (peak_dbfs / 20) / peak)).astype(np.float32)


def write_wav(path: str | Path, y: np.ndarray, sr: int) -> None:
    sf.write(str(path), y, sr, subtype="PCM_16")


def encode_ogg(wav_path: str | Path, ogg_path: str | Path, ffmpeg: str = "ffmpeg", quality: int = OGG_QUALITY) -> None:
    """Vorbis OGG from a WAV. Some engines leave a tiny gap when an OGG loops; the WAV loops seamlessly."""
    command = [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav_path), "-c:a", "libvorbis", "-q:a", str(quality)]
    # No console window: the backend runs detached, and a console program started from it would open one.
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        done = subprocess.run(
            [*command, str(ogg_path)], capture_output=True, text=True, creationflags=flags, check=False
        )
    except FileNotFoundError as e:
        raise AudioEncodeError(f"ffmpeg not found ({ffmpeg}); install it or set AIAS_FFMPEG") from e
    if done.returncode != 0:
        raise AudioEncodeError(f"ffmpeg failed ({done.returncode}): {done.stderr.strip()[-1000:]}")
