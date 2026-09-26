"""Image generation on the real ComfyUI and GPU. Run with `uv run pytest -m gpu -k image`."""

import io

import numpy as np
import pytest
from PIL import Image

pytestmark = pytest.mark.gpu


def test_image_sprite_transparent(real_client, run_job):
    real_client.post("/api/projects", json={"slug": "gpu-test", "name": "GPU test"}).raise_for_status()
    body = {
        "project": "gpu-test",
        "kind": "sprite",
        "description": "a small green slime monster",
        "count": 1,
        "seed": 42,
    }
    job = run_job(body)

    [asset] = job["assets"]
    processed = Image.open(io.BytesIO(real_client.get(asset["files"]["processed"]).content))
    assert processed.mode == "RGBA"
    a = np.asarray(processed)[..., 3]
    border = np.concatenate([a[:32].ravel(), a[-32:].ravel(), a[:, :32].ravel(), a[:, -32:].ravel()])
    assert border.max() == 0, "processed border (32 px) should be fully transparent"
    assert np.count_nonzero(a == 255) / a.size >= 0.01, "expected an opaque subject"
    raw_border = asset["meta"]["alpha_raw"]["border_mean"]
    print(f"\nraw border_mean={raw_border}, processed={asset['meta']['alpha_processed']}, {asset['meta']['timings']}")
