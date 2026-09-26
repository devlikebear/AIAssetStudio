"""How much of a song is vocals, measured by separating stems with torchaudio's Hybrid Demucs (Phase 4, T4.E.1).

Whisper is not used to detect vocals: on music it often invents lines such as "Thank you" (2026-09-24).
Needs torch, torchaudio and librosa, which the app does not install. Run it with a Python that has them (an
ai-toolkit virtual environment does):
    <that python.exe> scripts\\vocal_check.py <song files> [--out-dir DIR]
It first asks ComfyUI to free its models (POST /free, skip with --no-free): with ComfyUI holding them, Demucs ran
the GPU out of memory in earlier sessions. Separated stems go to --out-dir (default: a new temporary folder).
Ported from an earlier vocal_energy.py script.
"""

import argparse
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

SOURCES = ["drums", "bass", "other", "vocals"]


def free_comfyui(url: str) -> None:
    body = json.dumps({"unload_models": True, "free_memory": True}).encode()
    request = urllib.request.Request(f"{url}/free", data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(request, timeout=10).read()
        print(f"asked ComfyUI at {url} to free its models")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"could not reach ComfyUI at {url} ({e}); continuing")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("songs", nargs="+", type=Path)
    parser.add_argument("--out-dir", type=Path, help="where the separated stems go (default: a temporary folder)")
    parser.add_argument("--no-free", action="store_true", help="do not ask ComfyUI to free its models first")
    parser.add_argument("--comfy-url", default=os.environ.get("AIAS_COMFY_URL", "http://127.0.0.1:8188"))
    args = parser.parse_args()
    if not args.no_free:
        free_comfyui(args.comfy_url)
    out_dir = args.out_dir or Path(tempfile.mkdtemp(prefix="vocal_check_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    # Heavy, and only in the ai-toolkit environment: imported after the argument check and the /free.
    import librosa
    import soundfile as sf
    import torch
    from torchaudio.pipelines import HDEMUCS_HIGH_MUSDB_PLUS as bundle

    model = bundle.get_model().cuda().eval()
    sr = bundle.sample_rate  # 44100
    for path in args.songs:
        y, _ = librosa.load(str(path), sr=sr, mono=False)
        x = torch.tensor(y, dtype=torch.float32)
        if x.dim() == 1:
            x = x.unsqueeze(0).repeat(2, 1)
        ref = x.mean(0)
        x = (x - ref.mean()) / ref.std()
        segment, parts = sr * 10, []
        with torch.no_grad():
            for start in range(0, x.shape[1], segment):
                parts.append(model(x[:, start : start + segment].unsqueeze(0).cuda())[0].cpu())
        stems = torch.cat(parts, -1)  # (4 sources, 2 channels, samples)
        energy = stems.pow(2).mean((1, 2))
        share = {name: round((energy[i] / energy.sum()).item() * 100, 1) for i, name in enumerate(SOURCES)}
        # Share of 1 s windows where the vocal stem is within 20 dB of the mix.
        vocal = stems[3].pow(2).mean(0).unfold(0, sr, sr).mean(-1)
        mix = stems.sum(0).pow(2).mean(0).unfold(0, sr, sr).mean(-1)
        active = (10 * torch.log10(vocal / mix.clamp_min(1e-12)) > -20).float().mean().item() * 100
        print(f"{path.name}: vocals {share['vocals']}% of the energy {share} | vocal-active seconds {active:.0f}%")
        stem = path.stem
        sf.write(out_dir / f"{stem}_vocals.wav", (stems[3] * ref.std() + ref.mean()).T.numpy(), sr)
        sf.write(out_dir / f"{stem}_no_vocals.wav", (stems[:3].sum(0) * ref.std() + ref.mean()).T.numpy(), sr)
    print(f"stems: {out_dir}")


if __name__ == "__main__":
    main()
