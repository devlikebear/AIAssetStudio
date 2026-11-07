# Spike of 2026-11-01 (docs/plans/notes/studio-spike-2026-11-01.md). Kept as a reference, not run by the app.
"""Audiobook spike: narrate the 12 storybook pages with one voice, then a multi-voice dialogue from the manuscript."""
import json
import os
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

ROOT = Path(os.environ["SPIKE_BOOK_DIR"])
OUT = ROOT / "tts"
OUT.mkdir(exist_ok=True)
BOOK = json.loads((ROOT / "storyboard.json").read_text(encoding="utf-8"))
NARRATE = "Read slowly and calmly in a low voice, like an audiobook narrator telling a quiet sad story."

DIALOGUE = json.loads((ROOT / "dialogue.json").read_text(encoding="utf-8"))  # [[who, text], ...], never committed
VOICES = {
    "narrator": ("Sohee", NARRATE),
    "voice_a": ("Serena", "Speak lively and warmly, in a plain village manner."),
    "voice_b": ("Aiden", "Speak quietly and briefly, a reserved young man."),
    "mother": ("Vivian", "Speak in a trembling, grieving voice, barely holding back tears."),
}

log_path = OUT / "tts_log.jsonl"


def record(**row):
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(row, ensure_ascii=False), flush=True)


def speak(model, text, speaker, instruct):
    torch.cuda.reset_peak_memory_stats()
    t = time.monotonic()
    wavs, sr = model.generate_custom_voice(text=text, language="Korean", speaker=speaker, instruct=instruct)
    return np.asarray(wavs[0]), sr, time.monotonic() - t


t0 = time.monotonic()
model = Qwen3TTSModel.from_pretrained(
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa"
)
record(step="load", seconds=round(time.monotonic() - t0, 1), languages=model.get_supported_languages())

chunks, rate = [], 24000
for page in BOOK["pages"]:
    wav, rate, took = speak(model, page["text"], "Sohee", NARRATE)
    sf.write(OUT / f"page_{page['n']:02d}.wav", wav, rate)
    chunks += [wav, np.zeros(int(rate * 1.2), dtype=wav.dtype)]
    record(step="page", n=page["n"], audio_s=round(len(wav) / rate, 1), gen_s=round(took, 1),
           peak_vram_gb=round(torch.cuda.max_memory_allocated() / 2**30, 2))
sf.write(OUT / "audiobook_full.wav", np.concatenate(chunks), rate)

chunks = []
for i, (who, text) in enumerate(DIALOGUE):
    speaker, instruct = VOICES[who]
    wav, rate, took = speak(model, text, speaker, instruct)
    sf.write(OUT / f"dialogue_{i:02d}_{who}.wav", wav, rate)
    chunks += [wav, np.zeros(int(rate * 0.5), dtype=wav.dtype)]
    record(step="dialogue", i=i, who=who, speaker=speaker, audio_s=round(len(wav) / rate, 1), gen_s=round(took, 1))
sf.write(OUT / "dialogue_full.wav", np.concatenate(chunks), rate)
record(step="done", seconds=round(time.monotonic() - t0, 1))
