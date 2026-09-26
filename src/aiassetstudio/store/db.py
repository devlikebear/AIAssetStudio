"""SQLite storage for projects, jobs and assets (stdlib sqlite3, one shared connection)."""

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .models import Asset, Job, Project

SCHEMA_VERSION = 2

_SCHEMA = """
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
    animation_cloud INTEGER NOT NULL DEFAULT 0,
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

# version -> the SQL that takes a database of that version one step up. SQLite adds a NOT NULL column with a
# constant default in place, without rebuilding the table.
_UPGRADES = {
    1: "ALTER TABLE projects ADD COLUMN animation_cloud INTEGER NOT NULL DEFAULT 0;",
}

PROJECT_FIELDS = (
    "name",
    "style",
    "export_dir",
    "pixel_art",
    "logical_width",
    "logical_height",
    "icon_size",
    "max_colors",
    "palette",
    "reference_image",
    "animation_cloud",
)
JOB_FIELDS = ("params", "status", "stage", "error", "timings", "started_at", "finished_at")
_JSON_FIELDS = {"palette", "params", "timings", "files", "meta"}

_JOB_SELECT = "SELECT jobs.*, projects.slug AS project FROM jobs JOIN projects ON projects.id = jobs.project_id"
_ASSET_SELECT = "SELECT assets.*, projects.slug AS project FROM assets JOIN projects ON projects.id = assets.project_id"


class DuplicateSlug(ValueError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> str:
    return datetime.now(UTC).isoformat()


def _encode(field: str, value):
    if field in _JSON_FIELDS and value is not None:
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return int(value)
    return value


def _decode(row: sqlite3.Row) -> dict:
    d = dict(row)
    for field in _JSON_FIELDS & d.keys():
        if d[field] is not None:
            d[field] = json.loads(d[field])
    return d


def _check_fields(fields: dict, allowed: tuple[str, ...]) -> None:
    unknown = set(fields) - set(allowed)
    if unknown:
        raise ValueError(f"unknown fields: {sorted(unknown)}")


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Shared by the event loop and FastAPI's threadpool; every access goes through the lock.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"studio.db schema v{version} is newer than this app (v{SCHEMA_VERSION})")
        if version == 0:
            self._conn.executescript(f"BEGIN; {_SCHEMA} PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;")
            return
        for step in range(version, SCHEMA_VERSION):  # one transaction per step
            self._conn.executescript(f"BEGIN; {_UPGRADES[step]} PRAGMA user_version = {step + 1}; COMMIT;")

    def schema_version(self) -> int:
        with self._lock:
            return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def _write(self, sql: str, args=()) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, args)

    def _one(self, sql: str, args=()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def _all(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # --- projects -------------------------------------------------------------------------------

    def create_project(self, slug: str, name: str, style: str = "", export_dir: str | None = None, **spec) -> Project:
        _check_fields(spec, PROJECT_FIELDS)
        ts = now()
        fields = {"slug": slug, "name": name, "style": style, "export_dir": export_dir, **spec}
        fields |= {"created_at": ts, "updated_at": ts}
        cols = ", ".join(fields)
        marks = ", ".join("?" * len(fields))
        try:
            self._write(f"INSERT INTO projects ({cols}) VALUES ({marks})", [_encode(k, v) for k, v in fields.items()])
        except sqlite3.IntegrityError as e:
            raise DuplicateSlug(f"project {slug!r} already exists") from e
        return self.get_project(slug)

    def get_project(self, slug: str) -> Project | None:
        row = self._one("SELECT * FROM projects WHERE slug = ?", (slug,))
        return Project(**_decode(row)) if row else None

    def list_projects(self) -> list[Project]:
        return [Project(**_decode(r)) for r in self._all("SELECT * FROM projects ORDER BY slug")]

    def update_project(self, slug: str, **fields) -> Project | None:
        _check_fields(fields, PROJECT_FIELDS)
        if fields:
            fields["updated_at"] = now()
            sets = ", ".join(f"{k} = ?" for k in fields)
            self._write(
                f"UPDATE projects SET {sets} WHERE slug = ?", [*(_encode(k, v) for k, v in fields.items()), slug]
            )
        return self.get_project(slug)

    # --- jobs -----------------------------------------------------------------------------------

    def create_job(self, project_id: int, kind: str, family: str, params: dict) -> Job:
        job_id = new_id()
        self._write(
            "INSERT INTO jobs (id, project_id, kind, family, params, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'queued', ?)",
            (job_id, project_id, kind, family, _encode("params", params), now()),
        )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Job | None:
        row = self._one(f"{_JOB_SELECT} WHERE jobs.id = ?", (job_id,))
        return Job(**_decode(row)) if row else None

    def list_jobs(self, project: str | None = None, statuses: list[str] | None = None) -> list[Job]:
        where, args = [], []
        if project is not None:
            where.append("projects.slug = ?")
            args.append(project)
        if statuses:
            where.append(f"jobs.status IN ({', '.join('?' * len(statuses))})")
            args.extend(statuses)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        rows = self._all(f"{_JOB_SELECT}{clause} ORDER BY jobs.created_at DESC, jobs.rowid DESC", args)
        return [Job(**_decode(r)) for r in rows]

    def count_jobs(self, status: str) -> int:
        return self._one("SELECT COUNT(*) FROM jobs WHERE status = ?", (status,))[0]

    def next_queued_job(self, prefer_family: str | None = None) -> Job | None:
        """Oldest queued job, preferring `prefer_family` so jobs on the loaded model run back to back."""
        row = self._one(
            f"{_JOB_SELECT} WHERE jobs.status = 'queued'"
            " ORDER BY (jobs.family = ?) DESC, jobs.created_at, jobs.rowid LIMIT 1",
            (prefer_family,),
        )
        return Job(**_decode(row)) if row else None

    def update_job(self, job_id: str, **fields) -> Job | None:
        _check_fields(fields, JOB_FIELDS)
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            self._write(f"UPDATE jobs SET {sets} WHERE id = ?", [*(_encode(k, v) for k, v in fields.items()), job_id])
        return self.get_job(job_id)

    def mark_stale_running_failed(self) -> int:
        """Jobs left 'running' by a previous backend process can never finish; mark them failed."""
        cur = self._write(
            "UPDATE jobs SET status = 'failed', error = 'interrupted by restart', finished_at = ?"
            " WHERE status = 'running'",
            (now(),),
        )
        return cur.rowcount

    # --- assets ---------------------------------------------------------------------------------

    def create_asset(
        self,
        job_id: str,
        project_id: int,
        kind: str,
        files: dict[str, str],
        meta: dict,
        seed: int | None = None,
        asset_id: str | None = None,
    ) -> Asset:
        asset_id = asset_id or new_id()
        self._write(
            "INSERT INTO assets (id, job_id, project_id, kind, seed, files, meta, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (asset_id, job_id, project_id, kind, seed, _encode("files", files), _encode("meta", meta), now()),
        )
        return self.get_asset(asset_id)

    def get_asset(self, asset_id: str) -> Asset | None:
        row = self._one(f"{_ASSET_SELECT} WHERE assets.id = ?", (asset_id,))
        return Asset(**_decode(row)) if row else None

    def list_assets(
        self,
        project: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        job_id: str | None = None,
    ) -> list[Asset]:
        filters = {"projects.slug": project, "assets.kind": kind, "assets.status": status, "assets.job_id": job_id}
        where = [f"{col} = ?" for col, value in filters.items() if value is not None]
        args = [value for value in filters.values() if value is not None]
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        rows = self._all(f"{_ASSET_SELECT}{clause} ORDER BY assets.created_at, assets.rowid", args)
        return [Asset(**_decode(r)) for r in rows]

    def update_asset_status(self, asset_id: str, status: str) -> Asset | None:
        self._write("UPDATE assets SET status = ? WHERE id = ?", (status, asset_id))
        return self.get_asset(asset_id)

    def update_asset_meta(self, asset_id: str, meta: dict) -> Asset | None:
        self._write("UPDATE assets SET meta = ? WHERE id = ?", (_encode("meta", meta), asset_id))
        return self.get_asset(asset_id)
