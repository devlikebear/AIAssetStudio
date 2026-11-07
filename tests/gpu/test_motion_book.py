"""A two-page moving picture book on the real ComfyUI, speech pack and GPU. Run with `uv run pytest -m gpu -k motion`.

Takes about 8 minutes: two pictures, two clips and two takes, each model family clearing the GPU for the next.
"""

import dataclasses
import json
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from aiassetstudio.api.app import create_app
from aiassetstudio.config import load_settings
from aiassetstudio.narration import SPEECH_PACK
from aiassetstudio.packs.catalog import load_catalog
from aiassetstudio.packs.manager import ASSETS_DIR, pack_dir, pack_python
from aiassetstudio.packs.sidecar import SidecarManager

pytestmark = pytest.mark.gpu

TEST_PORT = 8767
STYLE = "Korean picture book illustration, ink wash and muted watercolor on paper."


def finished(client, job_id: str) -> dict:
    for _ in range(30):  # 15 minutes
        job = client.get(f"/api/jobs/{job_id}", params={"wait": 30}).json()
        if job["status"] in ("done", "failed", "cancelled"):
            break
    assert job["status"] == "done", job["error"]
    return job


@pytest.fixture
def book(tmp_path):
    base = load_settings()
    pack = load_catalog()[SPEECH_PACK]
    python, model = pack_python(base, SPEECH_PACK), pack_dir(base, SPEECH_PACK) / pack.model_dir
    if not python.is_file():
        pytest.skip("the speech pack is not installed")
    settings = dataclasses.replace(base, data_dir=tmp_path / "data", idle_free_seconds=3600)
    try:
        queue = httpx.get(f"{settings.comfy_url}/queue", timeout=3).raise_for_status().json()
    except httpx.HTTPError:
        pytest.skip(f"ComfyUI is not running at {settings.comfy_url}")
    if queue["queue_running"] or queue["queue_pending"]:
        pytest.skip("ComfyUI is busy with other prompts (another session may be using it)")
    command = [str(python), str(ASSETS_DIR / "tts_server.py"), "--model", str(model)]
    app = create_app(settings, sidecar=SidecarManager(settings, None, port=TEST_PORT, command=command))
    with TestClient(app, base_url=f"http://{settings.host}:{settings.port}") as client:
        client.app.state.services.db.save_install(SPEECH_PACK, version=pack.version, status="installed")
        yield client, settings


def test_two_page_motion_book(book):
    client, settings = book
    client.post("/api/projects", json={"slug": "gpu-motion", "name": "GPU", "style": STYLE}).raise_for_status()
    made = client.post("/api/books", json={"project": "gpu-motion", "title": "시험 영상"}).json()
    url = f"/api/books/{made['id']}"
    pages = [
        {
            "number": 1,
            "text": "강가의 집에 저녁이 왔다. 물은 조용했다.",
            "image_prompt": "An empty riverside house at dusk.",
        },
        {
            "number": 2,
            "text": "바람이 갈대를 흔들었다.",
            "image_prompt": "Tall reeds beside a wide river, nobody around.",
        },
    ]
    client.put(f"{url}/pages", json=pages).raise_for_status()
    for job_id in client.post(f"{url}/generate", json={"seed": 21}).json()["job_ids"]:
        finished(client, job_id)
    first, second = client.get(url).json()["pages"]
    for page, motion in ((first, "The river water flows gently."), (second, "The reeds sway in the wind.")):
        fields = {"status": "approved", "motion_prompt": motion}
        client.patch(f"/api/pages/{page['id']}", json=fields).raise_for_status()

    for job_id in client.post(f"{url}/clips", json={"seed": 22}).json()["job_ids"]:
        job = finished(client, job_id)
        print(f"\nclip: {job['timings']}, RAM free at start {job['assets'][0]['meta']['ram_free_gb']} GB")
    for job_id in client.post(f"{url}/narrate", json={"seed": 23}).json()["job_ids"]:
        finished(client, job_id)

    client.patch(f"/api/pages/{first['id']}", json={"clip_method": "full"}).raise_for_status()
    client.patch(f"/api/pages/{second['id']}", json={"clip_method": "head", "clip_head_s": 2}).raise_for_status()
    for page in client.get(url).json()["pages"]:
        fields = {"clip_status": "approved", "narration_status": "approved"}
        client.patch(f"/api/pages/{page['id']}", json=fields).raise_for_status()

    job = finished(client, client.post(f"{url}/export", json={"format": "mp4"}).json()["job_id"])
    [asset] = job["assets"]
    meta = asset["meta"]
    print(f"\nvideo: {meta['length_s']} s, {meta['frames']} frames, export {job['timings']}")
    assert meta["methods"] == {"1": "full", "2": "head"}
    assert meta["license_class"] == "research_only"

    path = Path(settings.data_dir) / "projects" / "gpu-motion" / "assets" / asset["id"] / "book.mp4"
    command = ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(path)]
    streams = {s["codec_type"]: s for s in json.loads(subprocess.check_output(command))["streams"]}
    assert int(streams["video"]["nb_read_frames"]) == meta["frames"]
    assert (streams["video"]["width"], streams["video"]["height"]) == (1280, 960)
    assert float(streams["audio"]["duration"]) == pytest.approx(meta["length_s"], abs=0.1)
