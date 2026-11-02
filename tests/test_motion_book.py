"""Clips and the book's video through the HTTP API, on the fake ComfyUI and a stand-in for the speech server."""

import numpy as np
import pytest
import soundfile as sf
from conftest import make_project
from fakes import FakeComfy
from test_audiobook import client, installed, narrate, sidecar  # noqa: F401

from aiassetstudio.comfy.graphs import WAN_LORA_HIGH, WAN_OUTPUT_NODE
from aiassetstudio.mcp_bridge import tools


def picture_book(client, *texts) -> dict:  # noqa: F811
    """A book whose pages have an approved picture and a motion."""
    make_project(client, style="ink wash")
    book = client.post("/api/books", json={"project": "demo", "title": "책"}).json()
    pages = [{"number": i, "text": t, "image_prompt": "x"} for i, t in enumerate(texts, start=1)]
    client.put(f"/api/books/{book['id']}/pages", json=pages).raise_for_status()
    jobs = client.post(f"/api/books/{book['id']}/generate", json={}).json()["job_ids"]
    for job in jobs:
        assert client.get(f"/api/jobs/{job}", params={"wait": 10}).json()["status"] == "done"
    for page in client.get(f"/api/books/{book['id']}").json()["pages"]:
        fields = {"status": "approved", "motion_prompt": "The water ripples."}
        client.patch(f"/api/pages/{page['id']}", json=fields).raise_for_status()
    return client.get(f"/api/books/{book['id']}").json()


def animate(client, book_id: str, **body) -> list[dict]:  # noqa: F811
    r = client.post(f"/api/books/{book_id}/clips", json=body)
    assert r.status_code == 202, r.text
    return [client.get(f"/api/jobs/{job}", params={"wait": 20}).json() for job in r.json()["job_ids"]]


def test_a_clip_starts_from_the_page_picture(client, fake_comfy: FakeComfy):  # noqa: F811
    book = picture_book(client, "글")
    [job] = animate(client, book["id"], seed=9)
    assert job["status"] == "done", job
    graph = fake_comfy.graphs[-1]
    assert graph["3"]["inputs"]["lora_name"] == WAN_LORA_HIGH
    assert graph["13"]["inputs"]["noise_seed"] == 9
    text = graph["8"]["inputs"]["text"]
    assert text.startswith("The water ripples. Everyone stays in exactly the same place")
    assert "ink wash" in text
    assert graph["11"]["inputs"]["image"].endswith(".png")
    assert WAN_OUTPUT_NODE in graph
    encode = fake_comfy.graphs[-2]  # the text encoder leaves memory before the video models load
    assert encode["8"] == graph["8"]
    assert encode["9"] == graph["9"]
    assert {n["class_type"] for k, n in encode.items() if k in ("20", "21")} == {"PreviewAny"}
    assert fake_comfy.free_calls[-1] == {"unload_models": True, "free_memory": False}

    [page] = client.get(f"/api/books/{book['id']}").json()["pages"]
    assert page["clip_status"] == "candidate"
    assert page["status"] == "approved"
    [clip] = page["clip_candidates"]
    assert clip["id"] == page["clip_asset_id"]
    assert clip["meta"]["picture"] == page["image_asset_id"]
    assert clip["meta"]["licenses"][0]["class"] == "open"
    assert sorted(clip["files"]) == ["first", "last", "mp4", "preview"]
    assert page["candidates"][0]["kind"] == "page_image"  # clips do not join the page's pictures


def test_someone_who_must_move_leaves_the_stay_in_place_words_out(client, fake_comfy):  # noqa: F811
    book = picture_book(client, "글")
    client.patch(f"/api/pages/{book['pages'][0]['id']}", json={"motion_still": False}).raise_for_status()
    animate(client, book["id"])
    assert "stays in exactly" not in fake_comfy.graphs[-1]["8"]["inputs"]["text"]


def test_a_clip_file_can_be_played_from_any_point(client):  # noqa: F811
    book = picture_book(client, "글")
    animate(client, book["id"])
    [page] = client.get(f"/api/books/{book['id']}").json()["pages"]
    url = page["clip_candidates"][0]["files"]["mp4"]
    whole = client.get(url)
    assert whole.headers["content-type"] == "video/mp4"
    part = client.get(url, headers={"Range": "bytes=10-19"})
    assert part.status_code == 206
    assert part.content == whole.content[10:20]


def test_clips_need_an_approved_picture_and_a_motion(client):  # noqa: F811
    make_project(client)
    book = client.post("/api/books", json={"project": "demo", "title": "책"}).json()
    client.put(
        f"/api/books/{book['id']}/pages", json=[{"number": 1, "text": "글", "image_prompt": "x"}]
    ).raise_for_status()
    assert client.post(f"/api/books/{book['id']}/clips", json={}).status_code == 409
    r = client.post(f"/api/books/{book['id']}/clips", json={"pages": [1]})
    assert r.status_code == 422
    assert "no approved picture" in r.json()["detail"]


def test_a_page_shown_as_its_picture_makes_no_clip(client):  # noqa: F811
    book = picture_book(client, "하나", "둘")
    client.patch(f"/api/pages/{book['pages'][0]['id']}", json={"clip_method": "still"}).raise_for_status()
    jobs = animate(client, book["id"])
    assert [j["params"]["page_number"] for j in jobs] == [2]


def test_a_new_motion_or_picture_sends_the_clip_back(client):  # noqa: F811
    book = picture_book(client, "글")
    animate(client, book["id"])
    page_id = book["pages"][0]["id"]
    r = client.patch(f"/api/pages/{page_id}", json={"motion_prompt": "The wind blows."}).json()
    assert (r["clip_status"], r["clip_asset_id"]) == ("draft", None)
    assert len(r["clip_candidates"]) == 1
    animate(client, book["id"])
    client.put(f"/api/books/{book['id']}/pages", json=[{"number": 1, "image_prompt": "new"}]).raise_for_status()
    [page] = client.get(f"/api/books/{book['id']}").json()["pages"]
    assert (page["clip_status"], page["clip_asset_id"]) == ("draft", None)


def test_the_way_a_page_is_shown_needs_a_verdict_it_can_keep(client):  # noqa: F811
    book = picture_book(client, "글")
    page_id = book["pages"][0]["id"]
    r = client.patch(f"/api/pages/{page_id}", json={"clip_status": "approved"})
    assert r.status_code == 422  # no clip yet
    r = client.patch(f"/api/pages/{page_id}", json={"clip_method": "still", "clip_status": "approved"})
    assert r.status_code == 200, r.text
    assert r.json()["clip_status"] == "approved"
    r = client.patch(f"/api/pages/{page_id}", json={"clip_head_s": 9})
    assert r.status_code == 422


def test_a_clip_of_another_page_cannot_be_chosen(client):  # noqa: F811
    book = picture_book(client, "하나", "둘")
    animate(client, book["id"])
    first, second = client.get(f"/api/books/{book['id']}").json()["pages"]
    r = client.patch(f"/api/pages/{first['id']}", json={"clip_asset_id": second["clip_asset_id"]})
    assert r.status_code == 422


def test_a_low_ram_start_is_recorded(client, fake_comfy, monkeypatch):  # noqa: F811
    import fakes

    monkeypatch.setitem(fakes.SYSTEM_STATS["system"], "ram_free", 3 * 2**30)
    book = picture_book(client, "글")
    [job] = animate(client, book["id"])
    assert "3.0 GB of RAM" in job["assets"][0]["meta"]["warnings"][0]


def test_the_video_needs_narration_and_a_way_to_show_every_page(client):  # noqa: F811
    book = picture_book(client, "글")
    r = client.post(f"/api/books/{book['id']}/export", json={"format": "mp4"})
    assert r.status_code == 409
    assert "narration of pages [1]" in r.json()["detail"]
    assert "the way to show pages [1]" in r.json()["detail"]
    r = client.post(f"/api/books/{book['id']}/export", json={"format": "mp4", "allow_draft": True})
    assert r.status_code == 409
    assert "both a chosen picture and narration" in r.json()["detail"]


def export_video(client, book_id: str, **body) -> dict:  # noqa: F811
    job_id = client.post(f"/api/books/{book_id}/export", json={"format": "mp4", **body}).json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}", params={"wait": 40}).json()
    assert job["status"] == "done", job
    return job["assets"][0]


@pytest.fixture
def real_length_take(sidecar):  # noqa: F811
    """Takes with sound: the loudness filter cannot read pure silence."""

    async def speak(body, timeout):
        tone = 0.1 * np.sin(2 * np.pi * 220 * np.arange(24000) / 24000)
        sf.write(body["out_path"], tone.astype(np.float32), 24000, subtype="PCM_16")
        return {"duration_s": 1.0, "sample_rate": 24000, "generate_s": 0.1, "peak_vram_gb": 4.0}

    sidecar.speak = speak


def test_the_video_names_a_limiting_license_and_uses_each_pages_way(client, real_length_take):  # noqa: F811
    installed(client)
    book = picture_book(client, "하나.", "둘.")
    animate(client, book["id"], pages=[1])
    narrate(client, book["id"])
    first, second = book["pages"]
    client.patch(f"/api/pages/{first['id']}", json={"clip_method": "head", "clip_head_s": 0.5}).raise_for_status()
    client.patch(f"/api/pages/{second['id']}", json={"clip_method": "still"}).raise_for_status()
    for page in (first, second):
        fields = {"clip_status": "approved", "narration_status": "approved"}
        r = client.patch(f"/api/pages/{page['id']}", json=fields)
        assert r.status_code == 200, r.text
    asset = export_video(client, book["id"])
    meta = asset["meta"]
    assert meta["format"] == "mp4"
    assert meta["methods"] == {"1": "head", "2": "still"}
    assert meta["license_class"] == "research_only"
    assert "Qwen-Image-2.1" in meta["warnings"][0]
    assert meta["length_s"] == pytest.approx(1 + 1.2 + 1 + 4, abs=0.1)
    assert client.get(asset["files"]["mp4"]).headers["content-type"] == "video/mp4"
    assert asset["files"]["preview"]


def test_a_draft_video_shows_the_picture_where_no_clip_exists(client, real_length_take):  # noqa: F811
    installed(client)
    book = picture_book(client, "하나.")
    narrate(client, book["id"])
    asset = export_video(client, book["id"], allow_draft=True)
    assert asset["meta"]["methods"] == {"1": "still"}
    assert asset["meta"]["unapproved_pages"] == [1]


async def test_the_tools_talk_about_clips(settings, fake_comfy):
    import httpx

    from aiassetstudio.api.app import create_app
    from aiassetstudio.mcp_bridge.studio_api import BackendError, StudioApi

    app = create_app(settings, comfy_transport=fake_comfy.transport)
    async with app.router.lifespan_context(app):
        api = StudioApi("http://127.0.0.1:8765", transport=httpx.ASGITransport(app=app))
        await api.create_project("demo", "Demo")
        book = await api.create_book("demo", "t", None)
        pages = await api.save_pages(book["id"], [{"number": 1, "text": "글", "image_prompt": "x"}])
        page_id = pages["pages"][0]["id"]
        with pytest.raises(BackendError, match="no page to animate"):
            await tools.generate_clips(api, book["id"])
        job_ids = await api.generate_pages(book["id"], None, None)
        await api.get_job(job_ids[0], wait=10)
        await api.update_page(page_id, status="approved")
        text = await tools.set_page_motion(api, page_id, "The water ripples.", clip_head_s=1.5)
        assert "clip [draft] 0 made, shown as full" in text
        queued = await tools.generate_clips(api, book["id"])
        job_id = queued.split(": ")[1].split(".")[0]
        result = await tools.get_job(api, job_id, wait_seconds=20)
        assert "last frame" in result[1]
        assert any("last frame" in str(item) for item in result if isinstance(item, str))
        shown = await tools.get_book(api, book["id"])
        assert any(isinstance(item, str) and "last frame of clip" in item for item in shown)
        await api.aclose()


def test_a_failed_model_read_is_tried_again_once(client, fake_comfy):  # noqa: F811
    book = picture_book(client, "글")
    fake_comfy.fail_once = "HostBuffer.read_file_slice failed"
    fake_comfy.free_calls.clear()
    [job] = animate(client, book["id"])
    assert job["status"] == "done", job
    assert "retried after" in job["assets"][0]["meta"]["warnings"][0]
    unload = {"unload_models": True, "free_memory": False}
    assert fake_comfy.free_calls[-2:] == [unload, unload]  # after the encode, and again before the second try


def test_another_failure_of_a_clip_is_not_tried_again(client, fake_comfy):  # noqa: F811
    book = picture_book(client, "글")
    fake_comfy.fail_once = "CUDA out of memory."
    [job] = animate(client, book["id"])
    assert job["status"] == "failed"
    assert "out of memory" in job["error"]
    [page] = client.get(f"/api/books/{book['id']}").json()["pages"]
    assert page["clip_status"] == "draft"
