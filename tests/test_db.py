import sqlite3

import pytest

from aiassetstudio.store.db import SCHEMA_VERSION, Database, DuplicateSlug

# studio.db as schema v1 made it (before projects.animation_cloud). db._SCHEMA is the newest schema only, so the
# upgrade test keeps its own copy of the old one.
_SCHEMA_V1 = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    style TEXT NOT NULL DEFAULT '',
    export_dir TEXT,
    pixel_art INTEGER NOT NULL DEFAULT 0,
    logical_width INTEGER,
    logical_height INTEGER,
    icon_size INTEGER,
    max_colors INTEGER,
    palette TEXT,
    reference_image TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    kind TEXT NOT NULL,
    family TEXT NOT NULL,
    params TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT,
    error TEXT,
    timings TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX jobs_status ON jobs(status, created_at);
CREATE INDEX jobs_project ON jobs(project_id, created_at);
CREATE TABLE assets (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    project_id INTEGER NOT NULL REFERENCES projects(id),
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    seed INTEGER,
    files TEXT NOT NULL,
    meta TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX assets_job ON assets(job_id);
CREATE INDEX assets_project ON assets(project_id, kind, status);
"""


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "studio.db")
    yield database
    database.close()


def test_project_round_trip(db):
    p = db.create_project("lastlight", "LAST LIGHT", style="dark fantasy", export_dir=r"C:\x")
    assert p.id > 0
    assert (p.slug, p.name, p.style, p.export_dir) == ("lastlight", "LAST LIGHT", "dark fantasy", r"C:\x")
    assert p.pixel_art is False and p.palette is None
    assert db.get_project("lastlight") == p
    assert db.get_project("nope") is None

    q = db.update_project("lastlight", style="한국어 화풍 ✓", pixel_art=True, palette=["#000000", "#ffffff"])
    assert q.style == "한국어 화풍 ✓"
    assert q.pixel_art is True
    assert q.palette == ["#000000", "#ffffff"]
    assert q.updated_at >= p.updated_at
    assert db.update_project("nope", name="x") is None
    with pytest.raises(ValueError):
        db.update_project("lastlight", created_at="2000-01-01")

    db.create_project("another", "Another")
    assert [p.slug for p in db.list_projects()] == ["another", "lastlight"]


def test_duplicate_slug_rejected(db):
    db.create_project("demo", "Demo")
    with pytest.raises(DuplicateSlug):
        db.create_project("demo", "Demo again")


def test_job_and_asset_round_trip(db):
    p = db.create_project("demo", "Demo")
    job = db.create_job(p.id, "image", "qwen", {"kind": "sprite", "description": "슬라임", "count": 2})
    assert job.status == "queued" and job.project == "demo"
    assert job.params == {"kind": "sprite", "description": "슬라임", "count": 2}
    assert db.get_job(job.id) == job

    running = db.update_job(job.id, status="running", stage="generating 1/2", timings={"a": 1.5})
    assert (running.status, running.stage, running.timings) == ("running", "generating 1/2", {"a": 1.5})
    with pytest.raises(ValueError):
        db.update_job(job.id, family="ace")

    asset = db.create_asset(
        job.id, p.id, "sprite", files={"raw": "projects/demo/assets/x/raw.png"}, meta={"seed": 7}, seed=7
    )
    assert (asset.status, asset.seed, asset.project) == ("candidate", 7, "demo")
    assert asset.files == {"raw": "projects/demo/assets/x/raw.png"}
    db.create_asset(job.id, p.id, "icon", files={}, meta={}, seed=8)
    assert [a.seed for a in db.list_assets(job_id=job.id)] == [7, 8]
    assert [a.seed for a in db.list_assets(project="demo", kind="icon")] == [8]

    selected = db.update_asset_status(asset.id, "selected")
    assert selected.status == "selected"
    assert [a.id for a in db.list_assets(status="selected")] == [asset.id]
    assert db.list_assets(project="other") == []

    assert [j.id for j in db.list_jobs(project="demo", statuses=["running"])] == [job.id]
    assert db.list_jobs(statuses=["queued"]) == []
    assert db.count_jobs("running") == 1


def test_next_queued_job_prefers_family_then_age(db):
    p = db.create_project("demo", "Demo")
    ace = db.create_job(p.id, "bgm", "ace", {})
    qwen1 = db.create_job(p.id, "image", "qwen", {})
    qwen2 = db.create_job(p.id, "image", "qwen", {})

    assert db.next_queued_job().id == ace.id
    assert db.next_queued_job(prefer_family="yue2").id == ace.id
    assert db.next_queued_job(prefer_family="qwen").id == qwen1.id
    db.update_job(qwen1.id, status="done")
    assert db.next_queued_job(prefer_family="qwen").id == qwen2.id
    db.update_job(qwen2.id, status="cancelled")
    assert db.next_queued_job(prefer_family="qwen").id == ace.id
    db.update_job(ace.id, status="running")
    assert db.next_queued_job() is None


def test_mark_stale_running_failed(db):
    p = db.create_project("demo", "Demo")
    stale = db.create_job(p.id, "image", "qwen", {})
    waiting = db.create_job(p.id, "image", "qwen", {})
    db.update_job(stale.id, status="running")

    assert db.mark_stale_running_failed() == 1
    failed = db.get_job(stale.id)
    assert (failed.status, failed.error) == ("failed", "interrupted by restart")
    assert failed.finished_at is not None
    assert db.get_job(waiting.id).status == "queued"


def test_schema_version_and_reopen(tmp_path):
    path = tmp_path / "studio.db"
    first = Database(path)
    assert first.schema_version() == SCHEMA_VERSION == 2
    first.create_project("demo", "Demo")
    first.close()
    second = Database(path)
    assert second.get_project("demo").name == "Demo"
    second.close()


def test_v1_database_is_upgraded_in_place(tmp_path):
    path = tmp_path / "studio.db"
    old = sqlite3.connect(path)
    old.executescript(f"BEGIN; {_SCHEMA_V1} PRAGMA user_version = 1; COMMIT;")
    old.execute(
        "INSERT INTO projects (slug, name, pixel_art, logical_width, created_at, updated_at)"
        " VALUES ('lastlight', 'LAST LIGHT', 1, 32, 't0', 't0')"
    )
    old.execute(
        "INSERT INTO jobs (id, project_id, kind, family, params, status, created_at)"
        " VALUES ('job1', 1, 'image', 'qwen', '{\"count\": 2}', 'done', 't1')"
    )
    old.commit()
    old.close()

    db = Database(path)
    assert db.schema_version() == SCHEMA_VERSION
    p = db.get_project("lastlight")
    assert (p.name, p.pixel_art, p.logical_width, p.animation_cloud) == ("LAST LIGHT", True, 32, False)
    job = db.get_job("job1")
    assert (job.status, job.params) == ("done", {"count": 2})
    assert db.update_project("lastlight", animation_cloud=True).animation_cloud is True
    db.close()
    reopened = Database(path)  # a v2 db opens as it is
    assert reopened.get_project("lastlight").animation_cloud is True
    reopened.close()


def test_new_projects_keep_animation_off(db):
    assert db.create_project("demo", "Demo").animation_cloud is False
    assert db.create_project("cloud", "Cloud", animation_cloud=True).animation_cloud is True
