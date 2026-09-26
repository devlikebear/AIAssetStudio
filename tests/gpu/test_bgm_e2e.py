"""Music on the real ComfyUI and GPU (Phase 4, T4.E.2). Run with `uv run pytest -m gpu -k bgm -s`.

A 60 s instrumental must come back as a loop of whole bars whose seam is no sharper than an ordinary sample step,
and a music job right after an image job must free ComfyUI's memory first.
"""

import io

import pytest
import soundfile as sf

pytestmark = pytest.mark.gpu

BPM = 100


def test_bgm_loop_and_family_switch(real_client, run_job):
    real_client.post("/api/projects", json={"slug": "gpu-bgm", "name": "GPU BGM"}).raise_for_status()
    brief = "dark fantasy battle theme, low string pizzicato, metallic percussion"
    song = {"project": "gpu-bgm", "brief": brief, "bpm": BPM, "seconds": 60, "count": 1, "seed": 2002}

    job = run_job(song, "bgm")
    [asset] = job["assets"]
    meta = asset["meta"]
    assert "loop" in meta, meta.get("loop_error")
    wav = sf.info(io.BytesIO(real_client.get(asset["files"]["loop_wav"]).content))
    bar = 60 / meta["loop"]["bpm"] * 4 * wav.samplerate  # the tempo the song has (detected), else the request
    assert abs(wav.frames - meta["loop"]["bars"] * bar) <= 1, (wav.frames, meta["loop"])
    assert meta["loop"]["seam_ratio"] <= 1
    assert "loop_ogg" in asset["files"], meta.get("ogg_error")
    print(
        f"\nsong {asset['id']}: raw {meta['raw_s']} s, trimmed {meta['trimmed_s']} s, loop {meta['loop']}, "
        f"generate {meta['timings']['generate']} s"
    )

    image = {"project": "gpu-bgm", "kind": "icon", "description": "a steel short sword", "count": 1, "seed": 1}
    run_job(image)
    after_image = run_job(song | {"seed": 2003}, "bgm")
    assert after_image["timings"].get("free_before") is True
    print(f"image -> bgm: free_before, generate {after_image['assets'][0]['meta']['timings']['generate']} s")
