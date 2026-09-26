"""A pixel-art project on the real ComfyUI and GPU (Phase 3, T3.D.2). Run with `uv run pytest -m gpu -k pixel -s`.

Sprites and an icon must come out at the project's logical size, with at most max_colors colors and alpha 0/255.
Then the first sprite becomes the project's reference image, and a sprite made with it must still be transparent.
"""

import io

import numpy as np
import pytest
from PIL import Image

from aiassetstudio.post.image import colors_used

pytestmark = pytest.mark.gpu

SPEC = {"pixel_art": True, "logical_width": 32, "logical_height": 32, "icon_size": 16, "max_colors": 12}


def check_pixel_asset(client, asset: dict, size: tuple[int, int]) -> Image.Image:
    processed = Image.open(io.BytesIO(client.get(asset["files"]["processed"]).content))
    assert processed.mode == "RGBA"
    assert processed.size == size
    alpha = np.asarray(processed)[..., 3]
    assert set(np.unique(alpha)) <= {0, 255}
    assert colors_used(processed) <= SPEC["max_colors"]
    assert np.count_nonzero(alpha) >= 0.1 * alpha.size, "expected a subject that fills part of the canvas"
    border = np.concatenate([alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]])
    assert border.max() == 0, "the 1-pixel margin must stay transparent"
    meta = asset["meta"]
    print(f"\n{asset['kind']} {asset['id']}: {meta['pixel']}, generate {meta['timings']['generate']} s")
    return processed


def test_pixel_project(real_client, run_job, tmp_path):
    real_client.post("/api/projects", json={"slug": "gpu-pixel", "name": "GPU pixel", **SPEC}).raise_for_status()

    sprites = run_job(
        {"project": "gpu-pixel", "kind": "sprite", "description": "a small green slime monster", "count": 2, "seed": 7},
    )
    assert len(sprites["assets"]) == 2
    checked = [check_pixel_asset(real_client, a, (32, 32)) for a in sprites["assets"]]
    first = checked[0]

    icon = run_job(
        {"project": "gpu-pixel", "kind": "icon", "description": "a red health potion", "count": 1, "seed": 7},
    )
    check_pixel_asset(real_client, icon["assets"][0], (16, 16))

    # The first sprite as the reference image (the studio enlarges the 32x32 copy x32 with nearest-neighbour).
    reference = tmp_path / "reference.png"
    first.save(reference)
    r = real_client.patch("/api/projects/gpu-pixel", json={"reference_image": str(reference)})
    r.raise_for_status()
    with_reference = run_job(
        {
            "project": "gpu-pixel",
            "kind": "sprite",
            "description": "a shadow wraith with glowing eyes",
            "count": 1,
            "seed": 7,
        },
    )
    [asset] = with_reference["assets"]
    check_pixel_asset(real_client, asset, (32, 32))
    assert asset["meta"]["reference"]["mode"] == "latent"
    # Qwen leaves the background at alpha 1..8 (sometimes a few specks up to ~21); an opaque background is ~255.
    assert asset["meta"]["alpha_raw"]["border_mean"] < 32, "the raw image with a reference should stay transparent"
    print(f"data dir: {tmp_path / 'data'}")
