import io
import time
from pathlib import Path

from conftest import ANIMATION_SPEC, make_project, run_animation_job, run_image_job
from fakes import SYSTEM_STATS
from PIL import Image

from aiassetstudio.api.app import allowed_hosts
from aiassetstudio.config import REPO_ROOT, Settings
from aiassetstudio.post.image import alpha_stats


def wait_until(client, job_id, *statuses, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in statuses or time.monotonic() > deadline:
            return job
        time.sleep(0.02)


def test_status(client):
    body = client.get("/api/status").json()
    assert body["backend"] == "ok"
    assert body["comfy"] == {
        "up": True,
        "url": "http://127.0.0.1:8188",
        "vram_free_mb": round(SYSTEM_STATS["devices"][0]["vram_free"] / 2**20),
        "ram_free_mb": round(SYSTEM_STATS["system"]["ram_free"] / 2**20),
    }
    assert body["preflight"]["qwen_turbo"] == {"ok": True, "missing_nodes": [], "missing_models": [], "reason": None}
    assert body["queue"] == {"running": None, "queued": 0, "current": None}
    assert body["gallery_url"] == "http://127.0.0.1:8765/"
    assert body["repo_dir"] == str(REPO_ROOT)
    animation = body["animation"]  # the test settings point at no sprite-gen and no codex
    assert (animation["ok"], animation["login"], animation["sprite_gen"], animation["codex"]) == (
        False,
        "missing",
        None,
        None,
    )
    assert "sprite-gen not found" in animation["reason"] and "codex CLI not found" in animation["reason"]


def test_status_when_comfyui_down(client, fake_comfy):
    fake_comfy.down = True
    body = client.get("/api/status").json()
    assert body["comfy"]["up"] is False
    assert "error" not in body["comfy"]
    assert body["preflight"]["qwen_turbo"]["reason"] == "comfyui_down"
    # ensure=true tries to start ComfyUI; the test settings point comfy_dir at a folder without it
    body = client.get("/api/status", params={"ensure": True}).json()
    assert body["comfy"]["up"] is False
    assert "ComfyUI not found" in body["comfy"]["error"]


def test_only_its_own_host_names(client):
    # A page that points its own domain at 127.0.0.1 (DNS rebinding) sends that domain as the Host: refused.
    for path in ("/api/health", "/api/projects", "/"):
        assert client.get(path, headers={"host": "attacker.example:8765"}).status_code == 400, path
    r = client.post("/api/projects", json={"slug": "x", "name": "x"}, headers={"host": "attacker.example"})
    assert r.status_code == 400
    assert client.get("/api/projects").json() == []  # nothing was created
    for host in ("127.0.0.1:8765", "localhost:8765", "localhost:5173"):  # 5173: the Vite dev server's proxy
        assert client.get("/api/health", headers={"host": host}).status_code == 200, host


def test_allowed_hosts():
    assert allowed_hosts(Settings()) == ["127.0.0.1", "localhost"]
    assert allowed_hosts(Settings(host="192.168.0.10")) == ["127.0.0.1", "localhost", "192.168.0.10"]
    assert allowed_hosts(Settings(host="::1")) == ["127.0.0.1", "localhost", "[::1]"]
    assert allowed_hosts(Settings(host="0.0.0.0")) == ["*"]  # every address: the user chose to be reachable


def test_network_paths_are_refused(client):
    # Opening \\server\share makes Windows connect (and sign in) to that server; refused before anything is read.
    share = r"\\server\share\Art"
    for body in ({"export_dir": share}, {"export_dir": "//server/share/Art"}, {"reference_image": share + r"\a.png"}):
        r = client.post("/api/projects", json={"slug": "net", "name": "x"} | body)
        assert r.status_code == 422 and "network path" in r.text, body
    make_project(client)
    assert client.patch("/api/projects/demo", json={"reference_image": share + r"\a.png"}).status_code == 422
    [asset] = run_image_job(client)["assets"]
    r = client.post(f"/api/assets/{asset['id']}/export", json={"dest_dir": share})
    assert r.status_code == 422 and "network path" in r.text


def test_gallery_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert client.get("/docs").status_code == 200  # the gallery mount must not shadow the API docs


def test_projects(client):
    p = make_project(client, style="cute chibi", export_dir=r"C:\games\demo\Art")
    assert (p["slug"], p["style"], p["export_dir"]) == ("demo", "cute chibi", r"C:\games\demo\Art")
    assert client.post("/api/projects", json={"slug": "demo", "name": "Again"}).status_code == 409
    assert client.post("/api/projects", json={"slug": "Bad Slug", "name": "x"}).status_code == 422
    assert client.post("/api/projects", json={"slug": "rel", "name": "x", "export_dir": "Art"}).status_code == 422
    assert client.post("/api/projects", json={"slug": "noname", "name": "  "}).status_code == 422

    assert [p["slug"] for p in client.get("/api/projects").json()] == ["demo"]
    assert client.get("/api/projects/demo").json()["name"] == "Demo"
    assert client.get("/api/projects/nope").status_code == 404

    r = client.patch("/api/projects/demo", json={"style": "dark fantasy", "name": None})
    assert r.status_code == 200
    assert (r.json()["style"], r.json()["name"]) == ("dark fantasy", "Demo")
    assert client.patch("/api/projects/demo", json={"export_dir": None}).json()["export_dir"] is None
    assert client.patch("/api/projects/nope", json={"style": "x"}).status_code == 404


PIXEL_SPEC = {"pixel_art": True, "logical_width": 32, "logical_height": 32, "max_colors": 12}


def test_pixel_spec(client):
    base = {"slug": "px", "name": "Pixel"}
    r = client.post("/api/projects", json=base | {"pixel_art": True, "logical_width": 32})
    assert r.status_code == 422
    assert "logical_height, max_colors" in r.text
    for bad in (["#12345", "#000000"], ["#000000"], ["red", "#000000"], ["#000000"] * 65):
        assert client.post("/api/projects", json=base | {"palette": bad}).status_code == 422, bad
    for field, value in (("logical_width", 4), ("logical_height", 257), ("icon_size", 7), ("max_colors", 65)):
        assert client.post("/api/projects", json=base | {field: value}).status_code == 422, field

    p = make_project(client, "px", **PIXEL_SPEC, palette=[" #AABBCC", "#112233"])
    assert (p["pixel_art"], p["logical_width"], p["max_colors"]) == (True, 32, 12)
    assert p["palette"] == ["#aabbcc", "#112233"]

    # A PATCH is checked against the whole project, not just the fields it sends.
    make_project(client, "plain")
    r = client.patch("/api/projects/plain", json={"pixel_art": True})
    assert r.status_code == 422
    assert "logical_width, logical_height, max_colors" in r.json()["detail"]
    assert client.patch("/api/projects/px", json={"max_colors": None}).status_code == 422
    r = client.patch("/api/projects/px", json={"icon_size": 16, "pixel_art": None}).json()
    assert (r["icon_size"], r["pixel_art"]) == (16, True)  # null leaves pixel_art as it is
    r = client.patch("/api/projects/px", json={"pixel_art": False, "max_colors": None, "palette": None}).json()
    assert (r["pixel_art"], r["max_colors"], r["palette"], r["logical_width"]) == (False, None, None, 32)
    # Decision (c), 2026-09-25: icon_size applies to projects that are not pixel art too.
    assert client.patch("/api/projects/plain", json={"icon_size": 64}).json()["icon_size"] == 64


def test_animation_cloud_setting(client):
    assert make_project(client)["animation_cloud"] is False  # off unless asked for
    assert make_project(client, "cloud", animation_cloud=True)["animation_cloud"] is True
    r = client.patch("/api/projects/demo", json={"animation_cloud": True}).json()
    assert r["animation_cloud"] is True
    r = client.patch("/api/projects/demo", json={"animation_cloud": None, "style": "x"}).json()
    assert r["animation_cloud"] is True  # null leaves it as it is
    assert client.patch("/api/projects/demo", json={"animation_cloud": False}).json()["animation_cloud"] is False


def test_reference_image(client, settings, tmp_path):
    source = tmp_path / "keeper.png"
    Image.new("RGBA", (24, 32), (200, 40, 40, 255)).save(source)
    original = source.read_bytes()

    p = make_project(client, reference_image=str(source))
    first = p["reference_image"]
    assert first.startswith("projects/demo/reference/") and first.endswith(".png")
    # Small pixel art is enlarged by a whole factor with nearest-neighbour (1024 // 32 = 32).
    assert Image.open(settings.data_dir / first).size == (24 * 32, 32 * 32)
    assert source.read_bytes() == original  # the original is only read
    r = client.get("/api/projects/demo/reference")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"

    painted = tmp_path / "painted.jpg"
    Image.new("RGB", (600, 400), (40, 90, 200)).save(painted)
    second = client.patch("/api/projects/demo", json={"reference_image": str(painted)}).json()["reference_image"]
    assert Image.open(settings.data_dir / second).size == (600, 400)  # not small: copied as it is
    assert (settings.data_dir / first).is_file()  # kept: assets made with it still point at it

    assert client.patch("/api/projects/demo", json={"reference_image": ""}).json()["reference_image"] is None
    assert client.get("/api/projects/demo/reference").status_code == 404

    (tmp_path / "notes.txt").write_text("not an image")
    Image.new("RGB", (8, 8)).save(tmp_path / "anim.gif")
    Image.new("L", (4097, 1)).save(tmp_path / "wide.png")
    bad = {
        "missing": str(tmp_path / "nope.png"),
        "not an image": str(tmp_path / "notes.txt"),
        "gif": str(tmp_path / "anim.gif"),
        "too large": str(tmp_path / "wide.png"),
        "relative": "keeper.png",
    }
    for why, path in bad.items():
        assert client.patch("/api/projects/demo", json={"reference_image": path}).status_code == 422, why
    r = client.post("/api/projects", json={"slug": "other", "name": "x", "reference_image": bad["missing"]})
    assert r.status_code == 422
    assert client.get("/api/projects/other").status_code == 404  # a bad reference creates nothing


def test_image_job_end_to_end(client):
    make_project(client)
    r = client.post("/api/jobs/image", json={"project": "demo", "kind": "sprite", "description": "a slime", "count": 2})
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    job = client.get(f"/api/jobs/{job_id}", params={"wait": 10}).json()
    assert job["status"] == "done", job
    assert job["project"] == "demo"
    assert len(job["assets"]) == 2

    for asset in job["assets"]:
        assert asset["files"] == {
            name: f"/api/assets/{asset['id']}/files/{name}" for name in ("raw", "processed", "preview")
        }
        for name, url in asset["files"].items():
            r = client.get(url)
            assert r.status_code == 200 and r.headers["content-type"] == "image/png", name
        processed = Image.open(io.BytesIO(client.get(asset["files"]["processed"]).content))
        stats = alpha_stats(processed)
        assert stats["border_mean"] == 0 and stats["border_max"] == 0
        assert asset["meta"]["alpha_processed"]["border_mean"] == 0

    first = job["assets"][0]["id"]
    assert client.patch(f"/api/assets/{first}", json={"status": "selected"}).json()["status"] == "selected"
    assert client.patch(f"/api/assets/{first}", json={"status": "bogus"}).status_code == 422
    assert [a["id"] for a in client.get("/api/assets", params={"status": "selected"}).json()] == [first]
    assert len(client.get("/api/assets", params={"project": "demo", "kind": "sprite"}).json()) == 2
    assert len(client.get("/api/assets", params={"job_id": job_id}).json()) == 2
    assert client.get(f"/api/assets/{first}").json()["status"] == "selected"
    assert client.get(f"/api/assets/{first}/files/nope").status_code == 404

    jobs = client.get("/api/jobs", params={"project": "demo"}).json()
    assert [j["id"] for j in jobs] == [job_id]
    assert client.get("/api/jobs", params={"status": "active"}).json() == []


def test_not_found(client):
    body = {"project": "nope", "kind": "sprite", "description": "x"}
    assert client.post("/api/jobs/image", json=body).status_code == 404
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.post("/api/jobs/nope/cancel").status_code == 404
    assert client.get("/api/jobs", params={"project": "nope"}).status_code == 404
    assert client.get("/api/assets/nope").status_code == 404
    assert client.get("/api/assets/nope/files/raw").status_code == 404
    assert client.get("/api/assets", params={"project": "nope"}).status_code == 404


def test_validation(client):
    make_project(client)
    base = {"project": "demo", "kind": "sprite", "description": "x"}
    assert client.post("/api/jobs/image", json=base | {"kind": "tileset"}).status_code == 422
    assert client.post("/api/jobs/image", json=base | {"count": 9}).status_code == 422
    assert client.post("/api/jobs/image", json=base | {"count": 0}).status_code == 422
    assert client.post("/api/jobs/image", json=base | {"description": "   "}).status_code == 422
    assert client.post("/api/jobs/image", json=base | {"description": "x" * 501}).status_code == 422
    assert client.post("/api/jobs/image", json=base | {"seed": -1}).status_code == 422
    assert client.get("/api/jobs", params={"status": "bogus"}).status_code == 422
    assert client.get("/api/jobs/x", params={"wait": 61}).status_code == 422
    assert client.get("/api/assets", params={"kind": "tileset"}).status_code == 422


def test_cancel(client, fake_comfy):
    make_project(client)
    fake_comfy.fail_with = "hang"
    body = {"project": "demo", "kind": "icon", "description": "a sword", "count": 2}
    running = client.post("/api/jobs/image", json=body).json()["job_id"]
    queued = client.post("/api/jobs/image", json=body).json()["job_id"]
    assert wait_until(client, running, "running")["status"] == "running"
    queue = client.get("/api/status").json()["queue"]
    assert (queue["running"], queue["queued"]) == (running, 1)
    assert queue["current"]["id"] == running
    assert queue["current"]["project"] == "demo"
    assert queue["current"]["elapsed_s"] >= 0
    assert {j["id"] for j in client.get("/api/jobs", params={"status": "active"}).json()} == {running, queued}

    assert client.post(f"/api/jobs/{queued}/cancel").json()["status"] == "cancelled"
    cancelled = client.post(f"/api/jobs/{running}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["assets"] == []
    [prompt_id] = fake_comfy.prompts
    assert fake_comfy.interrupts == [prompt_id]
    assert client.get("/api/status").json()["queue"] == {"running": None, "queued": 0, "current": None}


def run_bgm(client, **extra) -> dict:
    body = {"project": "demo", "brief": "cozy village theme", "bpm": 100, "seconds": 30, "count": 1, "seed": 3} | extra
    r = client.post("/api/jobs/bgm", json=body)
    assert r.status_code == 202, r.text
    job = client.get(f"/api/jobs/{r.json()['job_id']}", params={"wait": 20}).json()
    assert job["status"] == "done", job
    return job


def test_bgm_job_files_and_export(client, tmp_path):
    make_project(client)
    job = run_bgm(client)
    assert (job["kind"], job["family"]) == ("bgm", "ace")
    [asset] = job["assets"]
    assert asset["kind"] == "bgm"
    types = {"raw": "audio/flac", "loop_wav": "audio/wav", "loop_ogg": "audio/ogg"}
    assert set(asset["files"]) <= set(types) and {"raw", "loop_wav"} <= set(asset["files"])
    for role, url in asset["files"].items():
        r = client.get(url)
        assert r.status_code == 200 and r.headers["content-type"] == types[role], role

    dest = tmp_path / "Music"
    dest.mkdir()
    (dest / "village.ogg").write_bytes(b"taken")  # only the OGG name is taken: both files move to _2 together
    r = client.post(f"/api/assets/{asset['id']}/export", json={"dest_dir": str(dest), "name": "village"})
    paths = [Path(p) for p in r.json()["paths"]]
    assert {p.stem for p in paths} == {"village_2"}
    assert {p.suffix for p in paths} == {".wav", ".ogg"} if "loop_ogg" in asset["files"] else {".wav"}


def test_bgm_validation(client):
    make_project(client)
    base = {"project": "demo", "brief": "battle theme", "bpm": 100}
    assert client.post("/api/jobs/bgm", json=base | {"vocal": True}).status_code == 422  # lyrics needed
    assert client.post("/api/jobs/bgm", json=base | {"keyscale": "H minor"}).status_code == 422
    for field, value in (("bpm", 39), ("bpm", 201), ("seconds", 29), ("seconds", 241), ("count", 5)):
        assert client.post("/api/jobs/bgm", json=base | {field: value}).status_code == 422, field
    assert client.post("/api/jobs/bgm", json=base | {"project": "nope"}).status_code == 404
    r = client.post("/api/jobs/bgm", json=base | {"vocal": True, "lyrics": "[Verse]\nla la la", "loop": False})
    assert r.status_code == 202
    assert client.get(f"/api/jobs/{r.json()['job_id']}").json()["family"] == "yue2"


def test_animation_job_is_refused_without_the_cloud_setting(client):
    make_project(client, "px", **ANIMATION_SPEC)
    [sprite] = run_image_job(client, "px")["assets"]
    body = {"project": "px", "asset_id": sprite["id"]}
    assert client.post("/api/jobs/animation", json=body | {"project": "nope"}).status_code == 404
    r = client.post("/api/jobs/animation", json=body)
    assert r.status_code == 422
    assert "send its sprites to OpenAI" in r.json()["detail"] and "animation_cloud=true" in r.json()["detail"]
    assert client.get("/api/jobs", params={"project": "px", "status": "queued"}).json() == []

    client.patch("/api/projects/px", json={"animation_cloud": True})
    assert client.post("/api/jobs/animation", json=body | {"asset_id": "000000000000"}).status_code == 404
    assert client.post("/api/jobs/animation", json=body | {"count": 3}).status_code == 422
    [icon] = run_image_job(client, "px", kind="icon", description="a key")["assets"]
    r = client.post("/api/jobs/animation", json=body | {"asset_id": icon["id"]})
    assert r.status_code == 422 and "is a icon" in r.json()["detail"]
    make_project(client, "other", **ANIMATION_SPEC, animation_cloud=True)
    r = client.post("/api/jobs/animation", json={"project": "other", "asset_id": sprite["id"]})
    assert r.status_code == 404  # a sprite of another project
    make_project(client, "plain", animation_cloud=True)
    [plain] = run_image_job(client, "plain")["assets"]
    r = client.post("/api/jobs/animation", json={"project": "plain", "asset_id": plain["id"]})
    assert r.status_code == 422 and "pixel-art project" in r.json()["detail"]


def test_animation_job(animation_client):
    job = run_animation_job(animation_client)
    assert (job["kind"], job["family"]) == ("animation", "codex")
    assert job["params"]["description"] == "a slime"  # the sprite's description: the job's title
    [asset] = job["assets"]
    assert asset["kind"] == "animation"
    assert set(asset["files"]) == {"row", "json", "preview", "gif", "base"}
    gif = animation_client.get(asset["files"]["gif"])
    assert (gif.status_code, gif.headers["content-type"]) == (200, "image/gif")
    info = animation_client.get(asset["files"]["json"])
    assert info.headers["content-type"] == "application/json"
    assert info.json()["frames"] == 10
    kinds = animation_client.get("/api/assets", params={"project": "anim", "kind": "animation"}).json()
    assert [a["id"] for a in kinds] == [asset["id"]]


def test_animation_job_failure_is_recorded(animation_client, monkeypatch):
    monkeypatch.setenv("FAKE_SPRITEGEN_FAIL", "gen-set")
    make_project(animation_client, "anim", **ANIMATION_SPEC, animation_cloud=True)
    [sprite] = run_image_job(animation_client, "anim")["assets"]
    job_id = animation_client.post("/api/jobs/animation", json={"project": "anim", "asset_id": sprite["id"]}).json()
    job = animation_client.get(f"/api/jobs/{job_id['job_id']}", params={"wait": 20}).json()
    assert job["status"] == "failed"
    assert "sprite-gen gen-set failed" in job["error"] and "codex: not logged in" in job["error"]
    assert job["assets"] == []
