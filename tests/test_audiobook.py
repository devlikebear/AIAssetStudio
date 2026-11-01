"""Packs and narration through the HTTP API, on a stand-in for the speech server."""

import shutil
from pathlib import Path

import httpx
import numpy as np
import pytest
import soundfile as sf
from conftest import BASE_URL, make_project
from fastapi.testclient import TestClient

from aiassetstudio.api.app import create_app
from aiassetstudio.packs.catalog import load_catalog
from aiassetstudio.packs.manager import PackManager
from aiassetstudio.post.audio import load_audio

GALLERY = {"X-Studio-Client": "gallery"}
CLI = {"X-Studio-Client": "cli"}
RATE = 24000


class FakeSidecar:
    def __init__(self):
        self.running = False
        self.spoken: list[str] = []
        self.starts = 0
        self.stops = 0

    async def ensure(self):
        self.running = True
        self.starts += 1

    async def stop(self):
        self.running = False
        self.stops += 1

    async def aclose(self):
        self.running = False

    async def speak(self, body: dict, timeout: float) -> dict:
        self.spoken.append(body["text"])
        sf.write(body["out_path"], np.full(RATE, 0.1, dtype=np.float32), RATE, subtype="PCM_16")
        return {"duration_s": 1.0, "sample_rate": RATE, "generate_s": 0.1, "peak_vram_gb": 4.0}


@pytest.fixture
def sidecar():
    return FakeSidecar()


def nowhere(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500)


@pytest.fixture
def client(settings, fake_comfy, sidecar):
    async def no_commands(*args) -> int:
        return 0

    def make_packs(db):
        return PackManager(settings, db, transport=httpx.MockTransport(nowhere), run=no_commands)

    app = create_app(settings, comfy_transport=fake_comfy.transport, make_packs=make_packs, sidecar=sidecar)
    with TestClient(app, base_url=BASE_URL) as test_client:
        yield test_client


def services(client):
    return client.app.state.services


def installed(client) -> None:
    services(client).db.save_install("speech-ko", version=load_catalog()["speech-ko"].version, status="installed")


def make_book(client, *texts) -> dict:
    make_project(client)
    book = client.post("/api/books", json={"project": "demo", "title": "책"}).json()
    pages = [{"number": i, "text": t, "image_prompt": "x"} for i, t in enumerate(texts, start=1)]
    client.put(f"/api/books/{book['id']}/pages", json=pages).raise_for_status()
    return client.get(f"/api/books/{book['id']}").json()


def narrate(client, book_id: str, **body) -> list[dict]:
    r = client.post(f"/api/books/{book_id}/narrate", json=body)
    assert r.status_code == 202, r.text
    return [client.get(f"/api/jobs/{job}", params={"wait": 10}).json() for job in r.json()["job_ids"]]


def test_packs_are_listed_with_what_a_person_needs(client):
    [pack] = client.get("/api/packs").json()
    assert pack["id"] == "speech-ko"
    assert pack["status"] == "not_installed"
    assert pack["download_size"] > 4 * 2**30
    assert pack["licenses"][0]["accepted"] is False
    assert "상업 사용" in pack["licenses"][0]["summary_ko"]
    assert client.get("/api/packs/nothing").status_code == 404


@pytest.mark.parametrize("headers", [{}, CLI, {"X-Studio-Client": "mcp"}])
def test_only_the_gallery_records_consent(client, headers):
    r = client.post("/api/packs/speech-ko/accept", json={"licenses": ["apache-2.0"]}, headers=headers)
    assert r.status_code == 403
    assert services(client).db.list_consents("speech-ko") == []


def test_the_gallery_records_consent_per_license(client):
    r = client.post("/api/packs/speech-ko/accept", json={"licenses": ["apache-2.0"]}, headers=GALLERY)
    assert r.json()["licenses"][0]["accepted"] is True
    r = client.post("/api/packs/speech-ko/accept", json={"licenses": ["other"]}, headers=GALLERY)
    assert r.status_code == 422


def test_install_without_a_client_is_refused(client):
    assert client.post("/api/packs/speech-ko/install").status_code == 403
    assert client.post("/api/packs/speech-ko/cancel").status_code == 403
    assert client.delete("/api/packs/speech-ko").status_code == 403


@pytest.mark.parametrize("headers", [GALLERY, CLI])
def test_install_without_consent_says_where_to_agree(client, headers):
    r = client.post("/api/packs/speech-ko/install", headers=headers)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "consent_required"
    assert detail["gallery_url"].endswith("/#/packs/speech-ko")
    assert services(client).db.get_install("speech-ko") is None


def test_a_full_disk_refuses_the_install(client):
    client.post("/api/packs/speech-ko/accept", json={"licenses": ["apache-2.0"]}, headers=GALLERY)
    services(client).packs.disk_free = lambda path: 0
    r = client.post("/api/packs/speech-ko/install", headers=CLI)
    assert r.status_code == 507


def test_remove_ends_the_server_and_keeps_the_consent(client, sidecar):
    client.post("/api/packs/speech-ko/accept", json={"licenses": ["apache-2.0"]}, headers=GALLERY)
    installed(client)
    assert client.get("/api/packs/speech-ko").json()["status"] == "installed"
    r = client.delete("/api/packs/speech-ko", headers=CLI)
    assert r.status_code == 200
    assert r.json()["status"] == "not_installed"
    assert r.json()["licenses"][0]["accepted"] is True
    assert sidecar.stops == 1


def test_a_changed_license_is_shown(client):
    services(client).db.save_install("speech-ko", version="1.0.0", status="failed", error="license_changed: x")
    assert client.get("/api/packs/speech-ko").json()["license_changed"] is True


def test_status_names_the_packs(client):
    assert client.get("/api/status").json()["packs"] == {"speech-ko": "not_installed"}


def test_narrating_without_the_pack_points_to_the_gallery(client):
    book = make_book(client, "첫 쪽")
    r = client.post(f"/api/books/{book['id']}/narrate", json={})
    assert r.status_code == 409
    assert "/#/packs/speech-ko" in r.json()["detail"]


def test_narration_reads_the_page_with_its_terms(client, sidecar):
    installed(client)
    book = make_book(client, "남 영감이 왔다.")
    client.put(f"/api/books/{book['id']}/terms", json=[{"term": "남 영감", "spoken": "남영감"}]).raise_for_status()
    [job] = narrate(client, book["id"], seed=5)
    assert job["status"] == "done", job
    assert sidecar.spoken == ["남영감이 왔다."]
    assert sidecar.starts == 1

    [page] = client.get(f"/api/books/{book['id']}").json()["pages"]
    assert page["narration_status"] == "candidate"
    assert page["status"] == "draft"  # the picture's review is its own
    assert page["candidates"] == []
    [take] = page["narration_candidates"]
    assert take["id"] == page["narration_asset_id"]
    assert take["seed"] == 5
    assert take["meta"]["text"] == "남 영감이 왔다."
    assert take["meta"]["spoken_text"] == "남영감이 왔다."
    assert take["meta"]["licenses"][0]["class"] == "open"
    audio = client.get(take["files"]["wav"])
    assert audio.headers["content-type"] == "audio/wav"


def test_a_new_take_keeps_the_choice(client):
    installed(client)
    book = make_book(client, "글")
    narrate(client, book["id"])
    [first] = client.get(f"/api/books/{book['id']}").json()["pages"]
    narrate(client, book["id"], pages=[1])
    [page] = client.get(f"/api/books/{book['id']}").json()["pages"]
    assert page["narration_asset_id"] == first["narration_asset_id"]
    assert len(page["narration_candidates"]) == 2


def test_only_pages_in_draft_or_redo_are_narrated_by_default(client):
    installed(client)
    book = make_book(client, "하나", "둘")
    narrate(client, book["id"], pages=[1])
    jobs = narrate(client, book["id"])
    assert [j["params"]["page_number"] for j in jobs] == [2]
    assert client.post(f"/api/books/{book['id']}/narrate", json={}).status_code == 409


def test_a_page_without_text_is_not_narrated(client):
    installed(client)
    book = make_book(client, "")
    assert client.post(f"/api/books/{book['id']}/narrate", json={}).status_code == 422


def test_narration_is_reviewed_apart_from_the_picture(client):
    installed(client)
    book = make_book(client, "글")
    [page] = book["pages"]
    r = client.patch(f"/api/pages/{page['id']}", json={"narration_status": "approved"})
    assert r.status_code == 422  # nothing to approve yet

    narrate(client, book["id"])
    r = client.patch(f"/api/pages/{page['id']}", json={"narration_status": "redo", "narration_note": "더 천천히"})
    assert (r.json()["narration_status"], r.json()["narration_note"]) == ("redo", "더 천천히")
    assert r.json()["note"] is None
    r = client.patch(f"/api/pages/{page['id']}", json={"narration_status": "approved"})
    assert (r.json()["narration_status"], r.json()["narration_note"]) == ("approved", None)
    assert r.json()["status"] == "draft"
    assert client.get(f"/api/books/{book['id']}").json()["narration_counts"] == {"approved": 1}


def test_a_take_of_another_page_cannot_be_chosen(client):
    installed(client)
    book = make_book(client, "하나", "둘")
    narrate(client, book["id"])
    first, second = client.get(f"/api/books/{book['id']}").json()["pages"]
    r = client.patch(f"/api/pages/{first['id']}", json={"narration_asset_id": second["narration_asset_id"]})
    assert r.status_code == 422


def test_a_changed_text_sends_the_narration_back(client):
    installed(client)
    book = make_book(client, "글")
    narrate(client, book["id"])
    client.put(f"/api/books/{book['id']}/pages", json=[{"number": 1, "text": "새 글"}]).raise_for_status()
    [page] = client.get(f"/api/books/{book['id']}").json()["pages"]
    assert (page["narration_status"], page["narration_asset_id"]) == ("draft", None)
    assert len(page["narration_candidates"]) == 1


def test_mp3_needs_every_narration_approved(client):
    installed(client)
    book = make_book(client, "글")
    r = client.post(f"/api/books/{book['id']}/export", json={"format": "mp3"})
    assert r.status_code == 409
    assert "narration of pages [1]" in r.json()["detail"]
    r = client.post(f"/api/books/{book['id']}/export", json={"format": "mp3", "allow_draft": True})
    assert r.status_code == 409
    assert "no chosen narration" in r.json()["detail"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_mp3_export_records_where_each_page_starts(client):
    installed(client)
    book = make_book(client, "하나", "둘")
    narrate(client, book["id"])
    for page in client.get(f"/api/books/{book['id']}").json()["pages"]:
        client.patch(f"/api/pages/{page['id']}", json={"narration_status": "approved"}).raise_for_status()
    job_id = client.post(f"/api/books/{book['id']}/export", json={"format": "mp3"}).json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}", params={"wait": 20}).json()
    assert job["status"] == "done", job
    [asset] = job["assets"]
    assert asset["meta"]["format"] == "mp3"
    assert asset["meta"]["page_starts"] == [
        {"page": 1, "start_s": 0.0, "length_s": 1.0},
        {"page": 2, "start_s": 2.2, "length_s": 1.0},
    ]
    assert asset["meta"]["license_class"] == "open"
    assert asset["meta"]["warnings"] == []
    audio = client.get(asset["files"]["mp3"])
    assert audio.headers["content-type"] == "audio/mpeg"
    out = Path(services(client).settings.data_dir) / "out"
    r = client.post(f"/api/assets/{asset['id']}/export", json={"dest_dir": str(out.resolve()), "name": "book"})
    assert r.status_code == 200, r.text
    y, sr = load_audio(r.json()["paths"][0])
    assert abs(len(y) / sr - 3.2) < 0.1
