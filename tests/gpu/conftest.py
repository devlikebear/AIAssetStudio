import dataclasses
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from aiassetstudio.api.app import create_app
from aiassetstudio.config import load_settings

JOB_TIMEOUT = 600


@pytest.fixture
def real_client(tmp_path):
    """The app on a fresh data directory, talking to the real ComfyUI. Skips if ComfyUI is down or busy."""
    settings = dataclasses.replace(load_settings(), data_dir=tmp_path / "data", idle_free_seconds=3600)
    try:
        queue = httpx.get(f"{settings.comfy_url}/queue", timeout=3).raise_for_status().json()
    except httpx.HTTPError:
        pytest.skip(f"ComfyUI is not running at {settings.comfy_url}")
    if queue["queue_running"] or queue["queue_pending"]:
        pytest.skip("ComfyUI is busy with other prompts (another session may be using it)")
    with TestClient(create_app(settings), base_url=f"http://{settings.host}:{settings.port}") as client:
        yield client


@pytest.fixture
def run_job(real_client):
    """run_job(body, kind="image" or "bgm"): queue a job and wait until it ends; fails the test unless it is done."""

    def run(body: dict, kind: str = "image") -> dict:
        r = real_client.post(f"/api/jobs/{kind}", json=body)
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        deadline = time.monotonic() + JOB_TIMEOUT
        while True:
            job = real_client.get(f"/api/jobs/{job_id}", params={"wait": 30}).json()
            if job["status"] in ("done", "failed", "cancelled") or time.monotonic() > deadline:
                break
        assert job["status"] == "done", job["error"]
        return job

    return run
