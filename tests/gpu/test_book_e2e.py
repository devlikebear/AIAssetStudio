"""A two-page book on the real ComfyUI and GPU, sheet references included. Run with `uv run pytest -m gpu -k book`."""

import io
from pathlib import Path

import pytest
from PIL import Image

pytestmark = pytest.mark.gpu

STYLE = "Korean picture book illustration, ink wash and muted watercolor on paper."
FONT = Path(r"C:\Windows\Fonts\batang.ttc")


def finished(client, job_id: str) -> dict:
    for _ in range(20):  # 10 minutes
        job = client.get(f"/api/jobs/{job_id}", params={"wait": 30}).json()
        if job["status"] in ("done", "failed", "cancelled"):
            break
    return job


def test_two_page_book(real_client, run_job):
    client = real_client
    client.post("/api/projects", json={"slug": "gpu-book", "name": "GPU book", "style": STYLE}).raise_for_status()
    book = client.post("/api/books", json={"project": "gpu-book", "title": "시험 책"}).json()
    sheets = f"/api/books/{book['id']}/sheets"

    body = {"project": "gpu-book", "kind": "sprite", "count": 1, "seed": 11}
    sprite = run_job(body | {"description": "full body of a young woman with a long braid and a blue apron"})
    client.put(
        sheets,
        json=[
            {
                "kind": "character",
                "name": "Ada",
                "description": "a young woman with a long braid and a blue apron.",
                "asset_id": sprite["assets"][0]["id"],
            },
            {"kind": "place", "name": "Hall", "description": "a timber hall with a stone floor, open to a river."},
        ],
    ).raise_for_status()
    hall = next(s for s in client.get(f"/api/books/{book['id']}").json()["sheets"] if s["name"] == "Hall")
    job_id = client.post(f"/api/sheets/{hall['id']}/generate", json={"seed": 12}).json()["job_id"]
    assert finished(client, job_id)["status"] == "done"

    pages = [
        {
            "number": 1,
            "text": "강가의 집에 저녁이 왔다.",
            "image_prompt": "Exactly one person. Ada reads by the river.",
        },
        {
            "number": 2,
            "text": "그는 조용히 문을 닫았다.",
            "image_prompt": "Exactly one person. Ada closes a wooden door.",
        },
    ]
    body = [p | {"people": ["Ada"], "place": "Hall"} for p in pages]
    client.put(f"/api/books/{book['id']}/pages", json=body).raise_for_status()
    job_ids = client.post(f"/api/books/{book['id']}/generate", json={"seed": 13}).json()["job_ids"]
    for job_id in job_ids:
        assert finished(client, job_id)["status"] == "done"

    done = client.get(f"/api/books/{book['id']}").json()
    for page in done["pages"]:
        assert page["status"] == "candidate"
        [asset] = page["candidates"]
        assert [r["sheet"] for r in asset["meta"]["references"]] == ["Ada", "Hall"]
        image = Image.open(io.BytesIO(client.get(asset["files"]["processed"]).content))
        assert (image.mode, image.size) == ("RGB", (1184, 880))
        print(f"\npage {page['number']}: {asset['meta']['timings']}")
        client.patch(f"/api/pages/{page['id']}", json={"status": "approved"}).raise_for_status()

    if FONT.is_file():
        job = finished(client, client.post(f"/api/books/{book['id']}/export", json={}).json()["job_id"])
        assert job["status"] == "done", job["error"]
        assert client.get(job["assets"][0]["files"]["pdf"]).content[:4] == b"%PDF"
