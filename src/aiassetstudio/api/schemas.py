"""Request and response bodies of the HTTP API."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints, field_validator, model_validator

from ..comfy.graphs import KEYSCALES
from ..store.files import SLUG_PATTERN
from ..store.models import Asset, AssetStatus, Book, ClipMethod, Job, Page, Sheet, SheetKind, Term

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
PictureSide = Annotated[int, Field(ge=512, le=1536, multiple_of=16)]
PageNumber = Annotated[int, Field(ge=1, le=999)]
Style = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
LogicalSize = Annotated[int, Field(ge=8, le=256)]
ColorCount = Annotated[int, Field(ge=2, le=64)]
HexColor = Annotated[
    str,
    BeforeValidator(lambda v: v.strip().lower() if isinstance(v, str) else v),
    StringConstraints(pattern=r"^#[0-9a-f]{6}$"),
]
Palette = Annotated[list[HexColor], Field(min_length=2, max_length=64)]

PIXEL_REQUIRED = ("logical_width", "logical_height", "max_colors")


def missing_pixel_fields(project: dict) -> list[str]:
    """Spec fields a pixel-art project lacks (none if it is not pixel art)."""
    if not project.get("pixel_art"):
        return []
    return [name for name in PIXEL_REQUIRED if project.get(name) is None]


def _absolute_path(value: str | None, field: str) -> str | None:
    value = (value or "").strip()
    if value and not Path(value).is_absolute():
        raise ValueError(f"{field} must be an absolute path")
    # \\server\share: opening it makes Windows connect (and sign in) to that server. A mapped drive letter still works.
    if value.replace("/", "\\").startswith("\\\\"):
        raise ValueError(f"{field} must be a path on this PC, not a network path (\\\\server\\share)")
    return value or None


class _ProjectFields(BaseModel):
    export_dir: str | None = None  # absolute path; null or "" means none
    logical_width: LogicalSize | None = None  # sprite canvas of a pixel-art project
    logical_height: LogicalSize | None = None
    icon_size: LogicalSize | None = None  # square icon side; applies to every project (pixel art or not)
    max_colors: ColorCount | None = None
    palette: Palette | None = None  # "#rrggbb"
    reference_image: str | None = None  # absolute path of a PNG or JPEG, copied into the studio; null or "" = none

    @field_validator("export_dir", "reference_image")
    @classmethod
    def check_absolute(cls, value: str | None, info) -> str | None:
        return _absolute_path(value, info.field_name)


class ProjectCreate(_ProjectFields):
    slug: str = Field(pattern=SLUG_PATTERN)
    name: Name
    style: Style = ""
    pixel_art: bool = False
    animation_cloud: bool = False  # animation jobs may send this project's sprites to OpenAI (codex)

    @model_validator(mode="after")
    def check_pixel_spec(self) -> "ProjectCreate":
        if missing := missing_pixel_fields(self.model_dump()):
            raise ValueError(f"a pixel_art project needs {', '.join(missing)}")
        return self


class ProjectUpdate(_ProjectFields):
    """Omitted fields stay as they are. null leaves name, style, pixel_art and animation_cloud as they are and clears
    the others. The pixel-art requirement is checked on the merged project (app.update_project)."""

    name: Name | None = None
    style: Style | None = None
    pixel_art: bool | None = None
    animation_cloud: bool | None = None


class ImageJobCreate(BaseModel):
    project: str
    kind: Literal["sprite", "icon"]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    count: int = Field(4, ge=1, le=8)
    seed: int | None = Field(None, ge=0, le=2**53)


class BgmJobCreate(BaseModel):
    project: str
    brief: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    bpm: int = Field(ge=40, le=200)
    seconds: float = Field(90, ge=30, le=240)
    loop: bool = True
    vocal: bool = False  # True: a song with vocals (YuE2), which needs lyrics
    lyrics: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None
    keyscale: Literal[KEYSCALES] = "A minor"  # instrumentals only; the values ACE-Step accepts
    count: int = Field(2, ge=1, le=4)
    seed: int | None = Field(None, ge=0, le=2**53)

    @model_validator(mode="after")
    def check_lyrics(self) -> "BgmJobCreate":
        if self.vocal and not self.lyrics:
            raise ValueError("a song with vocals (vocal=true) needs lyrics")
        return self


class AnimationJobCreate(BaseModel):
    project: str
    asset_id: str  # a sprite of the project, which the animation moves
    count: int = Field(1, ge=1, le=2)  # candidates; each takes 1-3 minutes of codex


class JobCreated(BaseModel):
    job_id: str


class AssetUpdate(BaseModel):
    status: AssetStatus


class ExportRequest(BaseModel):
    dest_dir: str | None = None  # absolute path; defaults to the project's export_dir
    name: str | None = Field(None, max_length=200)  # file name without extension

    @field_validator("dest_dir")
    @classmethod
    def check_dest_dir(cls, value: str | None) -> str | None:
        return _absolute_path(value, "dest_dir")


class ExportResult(BaseModel):
    paths: list[str]


class AssetOut(Asset):
    """An asset whose `files` are download URLs instead of paths inside the data directory."""

    @classmethod
    def of(cls, asset: Asset) -> "AssetOut":
        urls = {name: f"/api/assets/{asset.id}/files/{name}" for name in asset.files}
        return cls(**(asset.model_dump() | {"files": urls}))


class JobOut(Job):
    assets: list[AssetOut] = Field(default_factory=list)


class BookCreate(BaseModel):
    project: str
    title: Name
    source: dict | None = None  # where the work comes from: {"system", "work_id", "label"}; shown, never fetched
    width: PictureSide = 1184  # the size of the 2026-11-01 trial, near 4:3; Qwen-Image keeps a 16 px grid
    height: PictureSide = 880


class BookUpdate(BaseModel):
    title: Name | None = None
    cover_page: PageNumber | None = None


class SourceRef(BaseModel):
    node_id: str
    content_version: int
    label: str = ""


class PageIn(BaseModel):
    number: PageNumber
    text: LongText = ""
    image_prompt: LongText = ""
    people: list[Name] = Field(default_factory=list)
    props: list[Name] = Field(default_factory=list)
    place: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)


class SheetIn(BaseModel):
    kind: SheetKind
    name: Name
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    asset_id: str | None = None


class TermIn(BaseModel):
    term: Name
    spoken: Name


class PageUpdate(BaseModel):
    status: Literal["approved", "redo", "draft"] | None = None
    note: LongText | None = None
    image_asset_id: str | None = None
    narration_status: Literal["approved", "redo", "draft"] | None = None
    narration_note: LongText | None = None
    narration_asset_id: str | None = None
    motion_prompt: LongText | None = None
    motion_still: bool | None = None
    clip_status: Literal["approved", "redo", "draft"] | None = None
    clip_note: LongText | None = None
    clip_asset_id: str | None = None
    clip_method: ClipMethod | None = None
    clip_head_s: float | None = Field(None, ge=0.5, le=5.0)


class GeneratePages(BaseModel):
    pages: list[PageNumber] | None = None  # default: the pages in draft or redo
    seed: int | None = Field(None, ge=0, le=2**53)  # default: a new one per page


class GenerateSheet(BaseModel):
    seed: int | None = Field(None, ge=0, le=2**53)


class JobsCreated(BaseModel):
    job_ids: list[str]


class CheckSources(BaseModel):
    versions: dict[str, int]  # node id -> its content_version now, read by the caller


class StalePage(BaseModel):
    number: int
    node_id: str
    label: str
    was: int
    now: int | None  # None: the caller did not list this passage


class BookExportRequest(BaseModel):
    format: Literal["pdf", "mp3", "mp4"] = "pdf"
    allow_draft: bool = False  # include pages that were not approved


class PageOut(Page):
    candidates: list[AssetOut] = Field(default_factory=list)
    narration_candidates: list[AssetOut] = Field(default_factory=list)
    clip_candidates: list[AssetOut] = Field(default_factory=list)


class SheetOut(Sheet):
    asset: AssetOut | None = None


class BookOut(Book):
    pages: list[PageOut]
    sheets: list[SheetOut]
    terms: list[Term]
    counts: dict[str, int]  # page status -> pages
    narration_counts: dict[str, int]  # narration status -> pages
    clip_counts: dict[str, int]  # clip status -> pages
    license_class: str | None  # of the chosen pictures; None until one is chosen


class PackAccept(BaseModel):
    licenses: list[str]  # the ids a person ticked


class PackLicenseOut(BaseModel):
    id: str
    name: str
    class_: str
    url: str
    summary_ko: str
    accepted: bool


class PackOut(BaseModel):
    id: str
    title: str
    feature: str
    version: str
    download_size: int
    tested: dict
    gated: bool
    licenses: list[PackLicenseOut]
    engine: str
    status: str  # not_installed, external (a ComfyUI is already in use), or installing, installed, failed, cancelled
    adopted: list[str]  # files that were already there; a removal leaves them
    stage: str | None
    error: str | None
    license_changed: bool  # the text online differs from what the catalog holds; a new Studio version must follow it
    installed_version: str | None
    log_tail: str
