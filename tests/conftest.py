from dataclasses import replace
from pathlib import Path

import pytest
from fakes import FakeComfy
from fastapi.testclient import TestClient

from aiassetstudio.api.app import create_app
from aiassetstudio.config import Settings

FAKE_SPRITEGEN = Path(__file__).parent / "fake_spritegen.py"
ANIMATION_SPEC = {"pixel_art": True, "logical_width": 32, "logical_height": 32, "max_colors": 12}
BASE_URL = "http://127.0.0.1:8765"  # the API answers only its own host names (TestClient's default is testserver)


@pytest.fixture
def settings(tmp_path) -> Settings:
    # comfy_dir, sprite_gen and codex_dir point nowhere so a test can never start the real ComfyUI, sprite-gen or
    # codex (tests that need sprite-gen use tests/fake_spritegen.py).
    return Settings(
        data_dir=tmp_path / "data",
        comfy_dir=tmp_path / "no-comfyui",
        idle_free_seconds=3600,
        image_timeout=10,
        sprite_gen=str(tmp_path / "no-sprite-gen" / "sprite-gen.exe"),
        codex_dir=str(tmp_path / "no-codex"),
    )


@pytest.fixture
def fake_comfy() -> FakeComfy:
    return FakeComfy()


@pytest.fixture
def client(settings, fake_comfy):
    app = create_app(settings, comfy_transport=fake_comfy.transport)
    with TestClient(app, base_url=BASE_URL) as test_client:  # the context manager runs the lifespan (DB, queue)
        yield test_client


@pytest.fixture
def animation_settings(settings, monkeypatch) -> Settings:
    """Settings whose sprite-gen is tests/fake_spritegen.py (which never calls codex)."""
    for var in ("FAKE_SPRITEGEN_FAIL", "FAKE_SPRITEGEN_SLOW", "FAKE_SPRITEGEN_HEIGHTS", "FAKE_SPRITEGEN_LOG"):
        monkeypatch.delenv(var, raising=False)
    return replace(settings, sprite_gen=str(FAKE_SPRITEGEN))


@pytest.fixture
def animation_client(animation_settings, fake_comfy):
    app = create_app(animation_settings, comfy_transport=fake_comfy.transport)
    with TestClient(app, base_url=BASE_URL) as test_client:
        yield test_client


def make_project(client, slug="demo", **extra) -> dict:
    r = client.post("/api/projects", json={"slug": slug, "name": "Demo", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def run_image_job(client, project="demo", **extra) -> dict:
    """Create an image job and wait for it (FakeComfy answers at once)."""
    body = {"project": project, "kind": "sprite", "description": "a slime", "count": 1} | extra
    job_id = client.post("/api/jobs/image", json=body).json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}", params={"wait": 10}).json()
    assert job["status"] == "done", job
    return job


def run_animation_job(client, project="anim", **extra) -> dict:
    """A pixel-art project with animations allowed, a sprite in it, and a finished animation job of that sprite."""
    if client.get(f"/api/projects/{project}").status_code == 404:
        make_project(client, project, **ANIMATION_SPEC, animation_cloud=True)
    [sprite] = run_image_job(client, project)["assets"]
    body = {"project": project, "asset_id": sprite["id"]} | extra
    r = client.post("/api/jobs/animation", json=body)
    assert r.status_code == 202, r.text
    job = client.get(f"/api/jobs/{r.json()['job_id']}", params={"wait": 20}).json()
    assert job["status"] == "done", job
    return job
