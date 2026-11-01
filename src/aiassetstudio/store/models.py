"""Records stored in studio.db."""

from typing import Literal

from pydantic import BaseModel

JobKind = Literal["image", "bgm", "animation", "page_image", "narration", "book_export"]
# qwen_turbo: the official Turbo checkpoint of books; tts: the speech pack's sidecar; codex: cloud, no GPU;
# none: on this PC, no GPU
Family = Literal["qwen", "qwen_turbo", "ace", "yue2", "tts", "codex", "none"]
JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]
AssetKind = Literal["sprite", "icon", "bgm", "animation", "page_image", "narration", "book_export"]
AssetStatus = Literal["candidate", "selected", "rejected"]
PageStatus = Literal["draft", "queued", "candidate", "approved", "redo"]
SheetKind = Literal["character", "place", "prop"]
PackInstallStatus = Literal["installing", "installed", "failed", "cancelled"]

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


class Book(BaseModel):
    """One work being made into a picture book. `source` says where it came from; Studio never reads that system."""

    id: str
    project_id: int
    project: str  # slug
    title: str
    source: dict | None = None
    width: int
    height: int
    cover_page: int | None = None  # page number whose picture is the cover; None = the first page
    created_at: str
    updated_at: str


class Page(BaseModel):
    id: str
    book_id: str
    number: int
    text: str = ""
    image_prompt: str = ""
    people: list[str] = []  # names of character sheets, the most important first
    props: list[str] = []  # names of prop sheets, or plain descriptions
    place: str | None = None  # name of a place sheet, or a plain description
    source_refs: list[dict] = []  # [{"node_id", "content_version", "label"}]: the passages the page rests on
    image_asset_id: str | None = None  # the chosen picture
    status: PageStatus = "draft"
    note: str | None = None  # the person's request for a redo, for the agent to read
    narration_asset_id: str | None = None  # the chosen take
    narration_status: PageStatus = "draft"  # reviewed apart from the picture: one can be approved alone
    narration_note: str | None = None
    created_at: str
    updated_at: str


class Sheet(BaseModel):
    """A character, place or prop the pages keep the same."""

    id: str
    book_id: str
    kind: SheetKind
    name: str
    description: str = ""
    asset_id: str | None = None  # its picture, used as a reference
    created_at: str


class Term(BaseModel):
    term: str
    spoken: str  # how to write it so the narrator says it right


class PackConsent(BaseModel):
    """A person agreed to this exact license text for this version of a pack."""

    pack_id: str
    pack_version: str
    license_id: str
    license_sha256: str
    accepted_at: str


class PackInstall(BaseModel):
    pack_id: str
    version: str
    status: PackInstallStatus
    stage: str | None = None
    error: str | None = None
    files: list[str] = []  # paths inside the pack's folder that the install made, all that a removal deletes
    installed_at: str | None = None
