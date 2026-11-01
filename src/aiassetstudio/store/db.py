"""SQLite storage for projects, jobs and assets (stdlib sqlite3, one shared connection)."""

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .models import Asset, Book, Job, PackConsent, PackInstall, Page, Project, Sheet, Term

SCHEMA_VERSION = 4

_BOOK_TABLES = """
CREATE TABLE books (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    title TEXT NOT NULL,
    source TEXT,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    cover_page INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX books_project ON books(project_id, created_at);
CREATE TABLE pages (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES books(id),
    number INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    image_prompt TEXT NOT NULL DEFAULT '',
    people TEXT NOT NULL DEFAULT '[]',
    props TEXT NOT NULL DEFAULT '[]',
    place TEXT,
    source_refs TEXT NOT NULL DEFAULT '[]',
    image_asset_id TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (book_id, number)
);
CREATE TABLE sheets (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES books(id),
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    asset_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (book_id, kind, name)
);
CREATE TABLE terms (
    book_id TEXT NOT NULL REFERENCES books(id),
    term TEXT NOT NULL,
    spoken TEXT NOT NULL,
    PRIMARY KEY (book_id, term)
);
"""

_PACK_TABLES = """
CREATE TABLE pack_consents (
    pack_id TEXT NOT NULL,
    pack_version TEXT NOT NULL,
    license_id TEXT NOT NULL,
    license_sha256 TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    PRIMARY KEY (pack_id, pack_version, license_id, license_sha256)
);
CREATE TABLE pack_installs (
    pack_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT,
    error TEXT,
    files TEXT NOT NULL DEFAULT '[]',
    installed_at TEXT
);
"""

_NARRATION_COLUMNS = """
ALTER TABLE pages ADD COLUMN narration_asset_id TEXT;
ALTER TABLE pages ADD COLUMN narration_status TEXT NOT NULL DEFAULT 'draft';
ALTER TABLE pages ADD COLUMN narration_note TEXT;
"""

_SCHEMA = (
    """
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
    + _BOOK_TABLES
    + _PACK_TABLES
    + _NARRATION_COLUMNS
)

# version -> the SQL that takes a database of that version one step up. SQLite adds a NOT NULL column with a
# constant default in place, without rebuilding the table.
_UPGRADES = {
    1: "ALTER TABLE projects ADD COLUMN animation_cloud INTEGER NOT NULL DEFAULT 0;",
    2: _BOOK_TABLES,
    3: _PACK_TABLES + _NARRATION_COLUMNS,
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
PAGE_FIELDS = ("text", "image_prompt", "people", "props", "place", "source_refs")
PAGE_STATE_FIELDS = ("status", "note", "image_asset_id", "narration_status", "narration_note", "narration_asset_id")
# A change to one of these makes the chosen picture out of date. `text` is not one: the picture still fits.
PAGE_PICTURE_FIELDS = ("image_prompt", "people", "props", "place")
PACK_INSTALL_FIELDS = ("version", "status", "stage", "error", "files", "installed_at")
_JSON_FIELDS = {"palette", "params", "timings", "files", "meta", "source", "people", "props", "source_refs"}

_JOB_SELECT = "SELECT jobs.*, projects.slug AS project FROM jobs JOIN projects ON projects.id = jobs.project_id"
_ASSET_SELECT = "SELECT assets.*, projects.slug AS project FROM assets JOIN projects ON projects.id = assets.project_id"
_BOOK_SELECT = "SELECT books.*, projects.slug AS project FROM books JOIN projects ON projects.id = books.project_id"


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

    def assets_with_meta(self, key: str, value: str) -> list[Asset]:
        """Assets whose meta has `key` = `value`, such as the candidates of one page. `key` is a constant of the
        caller, never input."""
        rows = self._all(
            f"{_ASSET_SELECT} WHERE json_extract(assets.meta, '$.{key}') = ? ORDER BY assets.created_at, assets.rowid",
            (value,),
        )
        return [Asset(**_decode(r)) for r in rows]

    # --- books ----------------------------------------------------------------------------------

    def create_book(self, project_id: int, title: str, source: dict | None, width: int, height: int) -> Book:
        book_id, ts = new_id(), now()
        self._write(
            "INSERT INTO books (id, project_id, title, source, width, height, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (book_id, project_id, title, _encode("source", source), width, height, ts, ts),
        )
        return self.get_book(book_id)

    def get_book(self, book_id: str) -> Book | None:
        row = self._one(f"{_BOOK_SELECT} WHERE books.id = ?", (book_id,))
        return Book(**_decode(row)) if row else None

    def list_books(self, project: str | None = None) -> list[Book]:
        clause, args = (" WHERE projects.slug = ?", (project,)) if project is not None else ("", ())
        rows = self._all(f"{_BOOK_SELECT}{clause} ORDER BY books.created_at DESC, books.rowid DESC", args)
        return [Book(**_decode(r)) for r in rows]

    def update_book(self, book_id: str, **fields) -> Book | None:
        _check_fields(fields, ("title", "cover_page"))
        if fields:
            fields["updated_at"] = now()
            sets = ", ".join(f"{k} = ?" for k in fields)
            self._write(f"UPDATE books SET {sets} WHERE id = ?", [*fields.values(), book_id])
        return self.get_book(book_id)

    def list_pages(self, book_id: str) -> list[Page]:
        rows = self._all("SELECT * FROM pages WHERE book_id = ? ORDER BY number", (book_id,))
        return [Page(**_decode(r)) for r in rows]

    def get_page(self, page_id: str) -> Page | None:
        row = self._one("SELECT * FROM pages WHERE id = ?", (page_id,))
        return Page(**_decode(row)) if row else None

    def save_pages(self, book_id: str, pages: list[dict]) -> list[Page]:
        """Add or change pages by number; pages not listed stay. A change to what a page shows sends it back to draft
        and drops the chosen picture (its candidates stay on the page); a change to its text does the same to the
        narration, which no longer says what the page says."""
        existing = {p.number: p for p in self.list_pages(book_id)}
        with self._lock, self._conn:
            for page in pages:
                _check_fields({k: v for k, v in page.items() if k != "number"}, PAGE_FIELDS)
                current = existing.get(page["number"])
                ts = now()
                if current is None:
                    cols = [
                        "id",
                        "book_id",
                        "number",
                        *(f for f in PAGE_FIELDS if f in page),
                        "created_at",
                        "updated_at",
                    ]
                    values = [new_id(), book_id, page["number"]]
                    values += [_encode(f, page[f]) for f in PAGE_FIELDS if f in page] + [ts, ts]
                    marks = ", ".join("?" * len(cols))
                    self._conn.execute(f"INSERT INTO pages ({', '.join(cols)}) VALUES ({marks})", values)
                    continue
                changes = {f: page[f] for f in PAGE_FIELDS if f in page and page[f] != getattr(current, f)}
                if not changes:
                    continue
                if any(f in changes for f in PAGE_PICTURE_FIELDS):
                    changes |= {"status": "draft", "image_asset_id": None}
                if "text" in changes:
                    changes |= {"narration_status": "draft", "narration_asset_id": None}
                changes["updated_at"] = ts
                sets = ", ".join(f"{k} = ?" for k in changes)
                self._conn.execute(
                    f"UPDATE pages SET {sets} WHERE id = ?", [*(_encode(k, v) for k, v in changes.items()), current.id]
                )
        return self.list_pages(book_id)

    def update_page(self, page_id: str, **fields) -> Page | None:
        _check_fields(fields, PAGE_STATE_FIELDS)
        if fields:
            fields["updated_at"] = now()
            sets = ", ".join(f"{k} = ?" for k in fields)
            self._write(f"UPDATE pages SET {sets} WHERE id = ?", [*fields.values(), page_id])
        return self.get_page(page_id)

    def release_idle_pages(self, book_id: str | None = None) -> None:
        """Pages marked queued with no job left for them: it failed, was cancelled or died with the backend."""
        clause, args = (" AND book_id = ?", (now(), book_id)) if book_id is not None else ("", (now(),))
        self._write(
            "UPDATE pages SET status = CASE WHEN image_asset_id IS NULL THEN 'draft' ELSE 'candidate' END,"
            " updated_at = ? WHERE status = 'queued' AND id NOT IN ("
            "SELECT json_extract(params, '$.page_id') FROM jobs WHERE kind = 'page_image'"
            " AND status IN ('queued', 'running') AND json_extract(params, '$.page_id') IS NOT NULL)" + clause,
            args,
        )

    def release_idle_narration(self, book_id: str | None = None) -> None:
        """The same for narration: pages queued for a narration job that is gone."""
        clause, args = (" AND book_id = ?", (now(), book_id)) if book_id is not None else ("", (now(),))
        self._write(
            "UPDATE pages SET narration_status = CASE WHEN narration_asset_id IS NULL THEN 'draft' ELSE 'candidate' END,"
            " updated_at = ? WHERE narration_status = 'queued' AND id NOT IN ("
            "SELECT json_extract(params, '$.page_id') FROM jobs WHERE kind = 'narration'"
            " AND status IN ('queued', 'running'))" + clause,
            args,
        )

    def list_sheets(self, book_id: str) -> list[Sheet]:
        rows = self._all("SELECT * FROM sheets WHERE book_id = ? ORDER BY kind, name", (book_id,))
        return [Sheet(**_decode(r)) for r in rows]

    def get_sheet(self, sheet_id: str) -> Sheet | None:
        row = self._one("SELECT * FROM sheets WHERE id = ?", (sheet_id,))
        return Sheet(**_decode(row)) if row else None

    def save_sheets(self, book_id: str, sheets: list[dict]) -> list[Sheet]:
        """Add or change sheets by kind and name; sheets not listed stay. An omitted asset_id keeps the picture."""
        with self._lock, self._conn:
            for sheet in sheets:
                self._conn.execute(
                    "INSERT INTO sheets (id, book_id, kind, name, description, asset_id, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (book_id, kind, name) DO UPDATE SET"
                    " description = excluded.description, asset_id = COALESCE(excluded.asset_id, asset_id)",
                    (
                        new_id(),
                        book_id,
                        sheet["kind"],
                        sheet["name"],
                        sheet.get("description", ""),
                        sheet.get("asset_id"),
                        now(),
                    ),
                )
        return self.list_sheets(book_id)

    def set_sheet_asset(self, sheet_id: str, asset_id: str) -> Sheet | None:
        self._write("UPDATE sheets SET asset_id = ? WHERE id = ?", (asset_id, sheet_id))
        return self.get_sheet(sheet_id)

    def list_terms(self, book_id: str) -> list[Term]:
        rows = self._all("SELECT term, spoken FROM terms WHERE book_id = ? ORDER BY term", (book_id,))
        return [Term(**dict(r)) for r in rows]

    def set_terms(self, book_id: str, terms: list[dict]) -> list[Term]:
        """Replace the book's whole list."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM terms WHERE book_id = ?", (book_id,))
            self._conn.executemany(
                "INSERT INTO terms (book_id, term, spoken) VALUES (?, ?, ?)",
                [(book_id, t["term"], t["spoken"]) for t in terms],
            )
        return self.list_terms(book_id)

    # --- feature packs --------------------------------------------------------------------------

    def add_consent(self, pack_id: str, version: str, license_id: str, license_sha256: str) -> None:
        self._write(
            "INSERT OR IGNORE INTO pack_consents (pack_id, pack_version, license_id, license_sha256, accepted_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (pack_id, version, license_id, license_sha256, now()),
        )

    def list_consents(self, pack_id: str) -> list[PackConsent]:
        rows = self._all("SELECT * FROM pack_consents WHERE pack_id = ? ORDER BY accepted_at", (pack_id,))
        return [PackConsent(**dict(r)) for r in rows]

    def get_install(self, pack_id: str) -> PackInstall | None:
        row = self._one("SELECT * FROM pack_installs WHERE pack_id = ?", (pack_id,))
        return PackInstall(**_decode(row)) if row else None

    def save_install(self, pack_id: str, **fields) -> PackInstall:
        """Add the pack's row, or change the fields given."""
        _check_fields(fields, PACK_INSTALL_FIELDS)
        if self.get_install(pack_id) is None:
            cols = ["pack_id", *fields]
            marks = ", ".join("?" * len(cols))
            values = [pack_id, *(_encode(k, v) for k, v in fields.items())]
            self._write(f"INSERT INTO pack_installs ({', '.join(cols)}) VALUES ({marks})", values)
        elif fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            values = [*(_encode(k, v) for k, v in fields.items()), pack_id]
            self._write(f"UPDATE pack_installs SET {sets} WHERE pack_id = ?", values)
        return self.get_install(pack_id)

    def delete_install(self, pack_id: str) -> None:
        self._write("DELETE FROM pack_installs WHERE pack_id = ?", (pack_id,))

    def mark_stale_installs_failed(self) -> int:
        """An install left running by a previous backend process stopped with it; its partial files stay to resume."""
        cur = self._write(
            "UPDATE pack_installs SET status = 'failed', stage = NULL, error = 'interrupted by restart'"
            " WHERE status = 'installing'"
        )
        return cur.rowcount
