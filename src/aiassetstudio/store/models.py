"""Records stored in studio.db."""

from typing import Literal

from pydantic import BaseModel

JobKind = Literal["image", "bgm", "animation"]
Family = Literal["qwen", "ace", "yue2", "codex"]  # codex: cloud, no GPU
JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]
AssetKind = Literal["sprite", "icon", "bgm", "animation"]
AssetStatus = Literal["candidate", "selected", "rejected"]

TERMINAL_STATUSES: tuple[JobStatus, ...] = ("done", "failed", "cancelled")


class Project(BaseModel):
    id: int
    slug: str
    name: str
    style: str = ""
    export_dir: str | None = None
    # Pixel-art spec and reference image: columns exist from schema v1, logic arrives in Phase 3.
    pixel_art: bool = False
    logical_width: int | None = None
    logical_height: int | None = None
    icon_size: int | None = None
    max_colors: int | None = None
    palette: list[str] | None = None  # "#rrggbb"
    reference_image: str | None = None
    animation_cloud: bool = False  # schema v2: animation jobs may send this project's sprites to OpenAI (codex)
    created_at: str
    updated_at: str


class Job(BaseModel):
    id: str
    project_id: int
    project: str  # slug
    kind: JobKind
    family: Family
    params: dict
    status: JobStatus
    stage: str | None = None
    error: str | None = None
    timings: dict | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class Asset(BaseModel):
    id: str
    job_id: str
    project_id: int
    project: str  # slug
    kind: AssetKind
    status: AssetStatus = "candidate"
    seed: int | None = None
    files: dict[str, str]  # file role ("raw", "processed", "preview") -> path relative to data_dir
    meta: dict
    created_at: str
