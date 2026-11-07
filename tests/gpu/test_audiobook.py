"""Narration on the real speech server and GPU, between image jobs on the real ComfyUI.

Run with `uv run pytest -m gpu -k audiobook`. Uses the speech pack installed in data/packs, or the Python and model folder
named by AIAS_TEST_TTS_PYTHON and AIAS_TEST_TTS_MODEL (the 2026-11-01 spike's, say); the test's own data folder has no
pack, so no consent or install runs here.
"""

import dataclasses
import io
import os
from pathlib import Path

import httpx
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from aiassetstudio.api.app import create_app
from aiassetstudio.config import load_settings
from aiassetstudio.narration import SPEECH_PACK
from aiassetstudio.packs.catalog import load_catalog
from aiassetstudio.packs.manager import ASSETS_DIR, pack_dir, pack_python
from aiassetstudio.packs.sidecar import SidecarManager

pytestmark = pytest.mark.gpu

TEST_PORT = 8767


def finished(client, job_id: str) -> dict:
    for _ in range(20):  # 10 minutes
        job = client.get(f"/api/jobs/{job_id}", params={"wait": 30}).json()
        if job["status"] in ("done", "failed", "cancelled"):
            break
    return job


def speech_command(settings) -> list[str]:
    pack = load_catalog()[SPEECH_PACK]
    python = Path(os.environ.get("AIAS_TEST_TTS_PYTHON") or pack_python(settings, SPEECH_PACK))
    model = Path(os.environ.get("AIAS_TEST_TTS_MODEL") or pack_dir(settings, SPEECH_PACK) / pack.model_dir)
    if not python.is_file() or not (model / "config.json").is_file():
        pytest.skip(f"no speech model: {python}, {model}")
    return [str(python), str(ASSETS_DIR / "tts_server.py"), "--model", str(model)]


@pytest.fixture
def audiobook(tmp_path):
    base = load_settings()
    command = speech_command(base)
    settings = dataclasses.replace(base, data_dir=tmp_path / "data", idle_free_seconds=3600)
    try:
        queue = httpx.get(f"{settings.comfy_url}/queue", timeout=3).raise_for_status().json()
    except httpx.HTTPError:
        pytest.skip(f"ComfyUI is not running at {settings.comfy_url}")
    if queue["queue_running"] or queue["queue_pending"]:
        pytest.skip("ComfyUI is busy with other prompts (another session may be using it)")
    sidecar = SidecarManager(settings, None, port=TEST_PORT, command=command)
    app = create_app(settings, sidecar=sidecar)
    with TestClient(app, base_url=f"http://{settings.host}:{settings.port}") as client:
        services = client.app.state.services
        services.db.save_install(SPEECH_PACK, version=load_catalog()[SPEECH_PACK].version, status="installed")
        yield client, sidecar


def image(client) -> dict:
    body = {"project": "gpu-audio", "kind": "sprite", "description": "a small red apple", "count": 1, "seed": 7}
    return finished(client, client.post("/api/jobs/image", json=body).json()["job_id"])


def test_narration_between_image_jobs(audiobook):
    client, sidecar = audiobook
    client.post("/api/projects", json={"slug": "gpu-audio", "name": "GPU audio"}).raise_for_status()
    book = client.post("/api/books", json={"project": "gpu-audio", "title": "시험 낭독"}).json()
    pages = [{"number": 1, "text": "강가의 집에 저녁이 왔다."}, {"number": 2, "text": "남 영감은 조용히 문을 닫았다."}]
    client.put(f"/api/books/{book['id']}/pages", json=pages).raise_for_status()
    client.put(f"/api/books/{book['id']}/terms", json=[{"term": "남 영감", "spoken": "남영감"}]).raise_for_status()

    assert image(client)["status"] == "done"

    job_ids = client.post(f"/api/books/{book['id']}/narrate", json={"seed": 3}).json()["job_ids"]
    jobs = [finished(client, job_id) for job_id in job_ids]
    assert [job["status"] for job in jobs] == ["done", "done"], [job["error"] for job in jobs]
    assert jobs[0]["timings"]["free_before"] is True  # the image models left the GPU first
    assert sidecar.running

    done = client.get(f"/api/books/{book['id']}").json()
    for page in done["pages"]:
        [take] = page["narration_candidates"]
        data, rate = sf.read(io.BytesIO(client.get(take["files"]["wav"]).content))
        assert rate == 24000
        assert len(data) / rate > 1
        print(f"\npage {page['number']}: {take['meta']['length_s']} s, {take['meta']['timings']}")
        client.patch(f"/api/pages/{page['id']}", json={"narration_status": "approved"}).raise_for_status()
    assert done["pages"][1]["narration_candidates"][0]["meta"]["spoken_text"] == "남영감은 조용히 문을 닫았다."

    assert image(client)["status"] == "done"  # back to ComfyUI: the speech server ended, and images still fit
    assert not sidecar.running

    job = finished(client, client.post(f"/api/books/{book['id']}/export", json={"format": "mp3"}).json()["job_id"])
    assert job["status"] == "done", job["error"]
    [asset] = job["assets"]
    starts = asset["meta"]["page_starts"]
    assert starts[1]["start_s"] == pytest.approx(starts[0]["length_s"] + 1.2, abs=0.01)
    data = client.get(asset["files"]["mp3"]).content
    assert data[:3] == b"ID3" or data[0] == 0xFF
    print(f"\nmp3: {len(data)} bytes, {starts}")
