"""Books through the HTTP API: pages, sheets, generation with references, review, sources and the PDF."""

from dataclasses import replace
from pathlib import Path

import pytest
from conftest import BASE_URL, make_project, run_image_job
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader

from aiassetstudio.api.app import create_app
from aiassetstudio.comfy.graphs import QWEN_BOOK_UNET
from aiassetstudio.store.db import SCHEMA_VERSION, Database

KOREAN_FONT = Path(r"C:\Windows\Fonts\batang.ttc")
PAGE = {"text": "Some text.", "image_prompt": "A scene."}


def make_book(client, project="demo", pages=2, **extra) -> dict:
    if client.get(f"/api/projects/{project}").status_code == 404:
        make_project(client, project, style="Ink wash.")
    r = client.post("/api/books", json={"project": project, "title": "A Book", **extra})
    assert r.status_code == 201, r.text
    book = r.json()
    if pages:
        body = [PAGE | {"number": n} for n in range(1, pages + 1)]
        book = client.put(f"/api/books/{book['id']}/pages", json=body).json()
    return book


def wait(client, job_id: str) -> dict:
    job = client.get(f"/api/jobs/{job_id}", params={"wait": 10}).json()
    assert job["status"] == "done", job
    return job


def generate(client, book: dict, **body) -> dict:
    r = client.post(f"/api/books/{book['id']}/generate", json=body)
    assert r.status_code == 202, r.text
    for job_id in r.json()["job_ids"]:
        wait(client, job_id)
    return client.get(f"/api/books/{book['id']}").json()


def approve_all(client, book: dict) -> None:
    for page in book["pages"]:
        r = client.patch(f"/api/pages/{page['id']}", json={"status": "approved"})
        assert r.status_code == 200, r.text


def test_book_has_defaults_and_can_be_listed(client):
    book = make_book(client, pages=0, source={"system": "linetta", "work_id": "w1", "label": "A Work"})
    assert (book["width"], book["height"]) == (1184, 880)
    assert book["source"]["label"] == "A Work"
    assert [b["id"] for b in client.get("/api/books", params={"project": "demo"}).json()] == [book["id"]]


def test_picture_side_keeps_the_grid(client):
    make_project(client)
    r = client.post("/api/books", json={"project": "demo", "title": "T", "width": 1000})
    assert r.status_code == 422


def test_unknown_book_and_project(client):
    assert client.get("/api/books/nope").status_code == 404
    assert client.post("/api/books", json={"project": "nope", "title": "T"}).status_code == 404


def test_pages_saved_by_number_leave_the_others(client):
    book = make_book(client)
    updated = client.put(f"/api/books/{book['id']}/pages", json=[{"number": 2, "text": "New."}]).json()
    assert [p["text"] for p in updated["pages"]] == ["Some text.", "New."]


def test_generation_stores_candidates_and_picks_the_first(client, fake_comfy):
    book = generate(client, make_book(client, pages=1))
    [page] = book["pages"]
    assert page["status"] == "candidate"
    assert page["image_asset_id"] == page["candidates"][0]["id"]
    candidate = page["candidates"][0]
    assert candidate["kind"] == "page_image"
    assert candidate["meta"]["page_number"] == 1
    assert candidate["meta"]["licenses"]
    latents = [n for g in fake_comfy.graphs for n in g.values() if n["class_type"] == "EmptyLatentImage"]
    assert (latents[0]["inputs"]["width"], latents[0]["inputs"]["height"]) == (1184, 880)
    saved = client.get(candidate["files"]["processed"]).content
    assert saved[:4] == b"\x89PNG"


def test_book_pictures_use_no_custom_node(client, fake_comfy):
    generate(client, make_book(client, pages=1))
    types = {n["class_type"] for g in fake_comfy.graphs for n in g.values()}
    assert "ManualSigmas" in types
    assert not {t for t in types if "Viggle" in t}
    unet = next(n for g in fake_comfy.graphs for n in g.values() if n["class_type"] == "UNETLoader")
    assert unet["inputs"]["unet_name"] == QWEN_BOOK_UNET


def test_generation_sends_references(client, fake_comfy):
    book = make_book(client, pages=0)
    sprite = run_image_job(client)["assets"][0]
    place = client.put(
        f"/api/books/{book['id']}/sheets",
        json=[
            {"kind": "character", "name": "Ada", "description": "a woman.", "asset_id": sprite["id"]},
            {"kind": "place", "name": "Hall", "description": "a hall."},
        ],
    ).json()["sheets"]
    hall = next(s for s in place if s["name"] == "Hall")
    wait(client, client.post(f"/api/sheets/{hall['id']}/generate", json={}).json()["job_id"])
    body = [PAGE | {"number": 1, "people": ["Ada"], "place": "Hall"}]
    book = client.put(f"/api/books/{book['id']}/pages", json=body).json()
    fake_comfy.uploads.clear()
    book = generate(client, book)
    assert len(fake_comfy.uploads) == 2
    encode = next(g for g in reversed(fake_comfy.graphs) if "20" in g)["5"]["inputs"]
    assert {k for k in encode if k.startswith("images.")} == {"images.image_1", "images.image_2"}
    assert "The second reference image shows the place Hall" in encode["prompt"]
    meta = book["pages"][0]["candidates"][0]["meta"]
    assert [r["sheet"] for r in meta["references"]] == ["Ada", "Hall"]


def test_sheet_picture_is_opaque_and_linked(client):
    book = make_book(client, pages=0)
    [sheet] = client.put(
        f"/api/books/{book['id']}/sheets", json=[{"kind": "place", "name": "Hall", "description": "a hall."}]
    ).json()["sheets"]
    job = wait(client, client.post(f"/api/sheets/{sheet['id']}/generate", json={}).json()["job_id"])
    [saved] = client.get(f"/api/books/{book['id']}").json()["sheets"]
    assert saved["asset_id"] == job["assets"][0]["id"]
    assert "nobody" in job["assets"][0]["meta"]["prompt"]


def test_character_sheet_is_drawn_as_a_sprite(client):
    book = make_book(client, pages=0)
    [sheet] = client.put(f"/api/books/{book['id']}/sheets", json=[{"kind": "character", "name": "Ada"}]).json()[
        "sheets"
    ]
    assert client.post(f"/api/sheets/{sheet['id']}/generate", json={}).status_code == 422


def test_sheet_asset_must_be_a_picture_of_the_project(client):
    book = make_book(client, pages=0)
    make_project(client, "other")
    sprite = run_image_job(client, "other")["assets"][0]
    body = [{"kind": "character", "name": "Ada", "asset_id": sprite["id"]}]
    assert client.put(f"/api/books/{book['id']}/sheets", json=body).status_code == 404


def test_saving_a_sheet_without_asset_keeps_its_picture(client):
    book = make_book(client, pages=0)
    sprite = run_image_job(client)["assets"][0]
    url = f"/api/books/{book['id']}/sheets"
    client.put(url, json=[{"kind": "character", "name": "Ada", "asset_id": sprite["id"]}])
    [sheet] = client.put(url, json=[{"kind": "character", "name": "Ada", "description": "new."}]).json()["sheets"]
    assert sheet["asset_id"] == sprite["id"]
    assert sheet["description"] == "new."


def test_regenerating_keeps_candidates_and_the_choice(client):
    book = generate(client, make_book(client, pages=1))
    first = book["pages"][0]["image_asset_id"]
    book = generate(client, book, pages=[1])
    [page] = book["pages"]
    assert len(page["candidates"]) == 2
    assert page["image_asset_id"] == first
    second = page["candidates"][1]["id"]
    r = client.patch(f"/api/pages/{page['id']}", json={"image_asset_id": second, "status": "approved"})
    assert r.json()["image_asset_id"] == second


def test_default_generation_takes_draft_and_redo_only(client):
    book = generate(client, make_book(client))
    [one, two] = book["pages"]
    client.patch(f"/api/pages/{one['id']}", json={"status": "approved"})
    client.patch(f"/api/pages/{two['id']}", json={"status": "redo", "note": "Her hair is wrong."})
    r = client.post(f"/api/books/{book['id']}/generate", json={})
    assert len(r.json()["job_ids"]) == 1
    wait(client, r.json()["job_ids"][0])
    pages = client.get(f"/api/books/{book['id']}").json()["pages"]
    assert [p["status"] for p in pages] == ["approved", "candidate"]
    assert pages[1]["note"] == "Her hair is wrong."


def test_nothing_to_generate(client):
    book = generate(client, make_book(client, pages=1))
    assert client.post(f"/api/books/{book['id']}/generate", json={}).status_code == 409


def test_page_without_prompt_and_unknown_page(client):
    book = make_book(client, pages=0)
    client.put(f"/api/books/{book['id']}/pages", json=[{"number": 1, "text": "Only words."}])
    assert client.post(f"/api/books/{book['id']}/generate", json={}).status_code == 422
    assert client.post(f"/api/books/{book['id']}/generate", json={"pages": [9]}).status_code == 404


def test_failed_job_lets_the_page_go_back(settings):
    from fakes import FakeComfy

    comfy = FakeComfy(fail_with="error")
    with TestClient(create_app(settings, comfy_transport=comfy.transport), base_url=BASE_URL) as client:
        book = make_book(client, pages=1)
        [job_id] = client.post(f"/api/books/{book['id']}/generate", json={}).json()["job_ids"]
        assert client.get(f"/api/jobs/{job_id}", params={"wait": 10}).json()["status"] == "failed"
        assert client.get(f"/api/books/{book['id']}").json()["pages"][0]["status"] == "draft"


def test_changing_what_a_page_shows_drops_the_approval(client):
    book = generate(client, make_book(client, pages=1))
    approve_all(client, book)
    url = f"/api/books/{book['id']}/pages"
    [page] = client.put(url, json=[{"number": 1, "image_prompt": "Another scene."}]).json()["pages"]
    assert page["status"] == "draft"
    assert page["image_asset_id"] is None
    assert len(page["candidates"]) == 1


def test_changing_only_the_text_keeps_the_approval(client):
    book = generate(client, make_book(client, pages=1))
    approve_all(client, book)
    url = f"/api/books/{book['id']}/pages"
    [page] = client.put(url, json=[{"number": 1, "text": "Better words."}]).json()["pages"]
    assert page["status"] == "approved"
    assert page["text"] == "Better words."


def test_approving_needs_a_picture_and_clears_the_note(client):
    book = make_book(client, pages=1)
    url = f"/api/pages/{book['pages'][0]['id']}"
    assert client.patch(url, json={"status": "approved"}).status_code == 422
    generate(client, book)
    client.patch(url, json={"status": "redo", "note": "Again."})
    assert client.patch(url, json={"status": "approved"}).json()["note"] is None


def test_a_page_cannot_choose_someone_elses_picture(client):
    book = generate(client, make_book(client))
    [one, two] = book["pages"]
    r = client.patch(f"/api/pages/{one['id']}", json={"image_asset_id": two["image_asset_id"]})
    assert r.status_code == 422


def test_check_sources_finds_changed_and_unlisted_passages(client):
    book = make_book(client, pages=0)
    refs = [{"node_id": "n1", "content_version": 3, "label": "One"}, {"node_id": "n2", "content_version": 5}]
    body = [PAGE | {"number": 1, "source_refs": refs}, PAGE | {"number": 2, "source_refs": refs[:1]}]
    client.put(f"/api/books/{book['id']}/pages", json=body)
    r = client.post(f"/api/books/{book['id']}/check-sources", json={"versions": {"n1": 3, "n2": 5}})
    assert r.json() == []
    r = client.post(f"/api/books/{book['id']}/check-sources", json={"versions": {"n1": 4}})
    stale = [(s["number"], s["node_id"], s["was"], s["now"]) for s in r.json()]
    assert stale == [(1, "n1", 3, 4), (1, "n2", 5, None), (2, "n1", 3, 4)]


def test_license_class_of_the_book(client):
    assert make_book(client, pages=1)["license_class"] is None
    book = generate(client, make_book(client, pages=1))
    assert book["license_class"] == "research_only"


def test_export_refuses_unapproved_pages(client):
    book = generate(client, make_book(client))
    r = client.post(f"/api/books/{book['id']}/export", json={})
    assert r.status_code == 409
    assert "[1, 2]" in r.json()["detail"]


def test_export_with_nothing_to_show(client):
    assert client.post(f"/api/books/{make_book(client, pages=0)['id']}/export", json={}).status_code == 409
    book = make_book(client, pages=1)
    assert client.post(f"/api/books/{book['id']}/export", json={"allow_draft": True}).status_code == 409


@pytest.fixture
def pdf_client(settings, fake_comfy, tmp_path):
    if not KOREAN_FONT.is_file():
        pytest.skip("needs a Korean font")
    app = create_app(replace(settings, book_font=str(KOREAN_FONT)), comfy_transport=fake_comfy.transport)
    with TestClient(app, base_url=BASE_URL) as client:
        yield client


def test_export_writes_a_pdf_with_real_text(pdf_client, settings, tmp_path):
    client = pdf_client
    book = make_book(client, pages=0, source={"label": "A Work"})
    body = [{"number": 1, "text": "강은 위쪽 마을이 버린 것들을 데려왔다.", "image_prompt": "A river."}]
    book = generate(client, client.put(f"/api/books/{book['id']}/pages", json=body).json())
    approve_all(client, book)
    job = wait(client, client.post(f"/api/books/{book['id']}/export", json={}).json()["job_id"])
    [asset] = job["assets"]
    assert asset["kind"] == "book_export"
    assert asset["meta"]["license_class"] == "research_only"
    assert any("license" in w for w in asset["meta"]["warnings"])
    assert job["family"] == "none"
    r = client.get(asset["files"]["pdf"])
    assert r.headers["content-type"] == "application/pdf"
    out = tmp_path / "out.pdf"
    out.write_bytes(r.content)
    pages = PdfReader(out).pages
    assert len(pages) == 3  # cover, the page, colophon
    assert "A Book" in pages[0].extract_text()
    assert "강은 위쪽 마을이" in pages[1].extract_text().replace("\n", " ")
    assert "Qwen Research License" in pages[2].extract_text()
    assert "A Work" in pages[2].extract_text()

    dest = tmp_path / "exports"
    r = client.post(f"/api/assets/{asset['id']}/export", json={"dest_dir": str(dest), "name": "book"})
    assert r.status_code == 200, r.text
    assert Path(r.json()["paths"][0]).suffix == ".pdf"


def test_export_can_include_drafts(pdf_client):
    client = pdf_client
    book = generate(client, make_book(client, pages=1))
    job = wait(client, client.post(f"/api/books/{book['id']}/export", json={"allow_draft": True}).json()["job_id"])
    assert job["assets"][0]["meta"]["unapproved_pages"] == [1]


def test_cover_page_is_used(pdf_client, settings):
    client = pdf_client
    book = generate(client, make_book(client))
    client.patch(f"/api/books/{book['id']}", json={"cover_page": 2})
    approve_all(client, book)
    job = wait(client, client.post(f"/api/books/{book['id']}/export", json={}).json()["job_id"])
    assert job["assets"][0]["meta"]["pages"] == [1, 2]


def test_missing_font_fails_the_job_with_a_clear_error(settings, fake_comfy):
    app = create_app(replace(settings, book_font="C:/no/such/font.ttf"), comfy_transport=fake_comfy.transport)
    with TestClient(app, base_url=BASE_URL) as client:
        book = generate(client, make_book(client, pages=1))
        approve_all(client, book)
        job_id = client.post(f"/api/books/{book['id']}/export", json={}).json()["job_id"]
        job = client.get(f"/api/jobs/{job_id}", params={"wait": 10}).json()
        assert job["status"] == "failed"
        assert "AIAS_BOOK_FONT" in job["error"]


def test_version_2_database_upgrades(tmp_path):
    import sqlite3

    path = tmp_path / "studio.db"
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT); PRAGMA user_version = 2;")
    conn.close()
    db = Database(path)
    assert db.schema_version() == SCHEMA_VERSION
    assert db.list_books() == []
    db.close()


CLIP_COLUMNS = (
    "motion_prompt",
    "motion_still",
    "clip_asset_id",
    "clip_status",
    "clip_note",
    "clip_method",
    "clip_head_s",
)


def test_version_3_database_keeps_its_pages(tmp_path):
    """The step that adds packs and narration, on a book made by the version before it."""
    path = tmp_path / "studio.db"
    db = Database(path)
    project = db.create_project("demo", "Demo")
    book = db.create_book(project.id, "t", None, 1184, 880)
    db.save_pages(book.id, [{"number": 1, "text": "a"}])
    db._conn.executescript(
        "DROP TABLE pack_consents; DROP TABLE pack_installs; ALTER TABLE pages DROP COLUMN narration_asset_id;"
        "ALTER TABLE pages DROP COLUMN narration_status; ALTER TABLE pages DROP COLUMN narration_note;"
        + "".join(f"ALTER TABLE pages DROP COLUMN {column};" for column in CLIP_COLUMNS)
        + "PRAGMA user_version = 3;"
    )
    db.close()
    db = Database(path)
    assert db.schema_version() == SCHEMA_VERSION
    [page] = db.list_pages(book.id)
    assert (page.text, page.narration_status, page.narration_asset_id) == ("a", "draft", None)
    assert db.get_install("speech-ko") is None
    db.close()


def test_a_new_text_sends_the_narration_back_and_keeps_the_picture(tmp_path):
    db = Database(tmp_path / "studio.db")
    project = db.create_project("demo", "Demo")
    book = db.create_book(project.id, "t", None, 1184, 880)
    [page] = db.save_pages(book.id, [{"number": 1, "text": "a", "image_prompt": "p"}])
    db.update_page(
        page.id, status="approved", image_asset_id="pic", narration_status="approved", narration_asset_id="n"
    )
    [page] = db.save_pages(book.id, [{"number": 1, "text": "b"}])
    assert (page.status, page.image_asset_id) == ("approved", "pic")
    assert (page.narration_status, page.narration_asset_id) == ("draft", None)
    db.close()


def test_images_on_disk_are_rgb(client, settings):
    book = generate(client, make_book(client, pages=1))
    project = client.get("/api/projects/demo").json()
    asset_id = book["pages"][0]["image_asset_id"]
    path = settings.data_dir / "projects" / project["slug"] / "assets" / asset_id / "processed.png"
    with Image.open(path) as image:
        assert image.mode == "RGB"
    assert (path.parent / "raw.png").is_file()
