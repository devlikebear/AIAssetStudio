"""Feature packs: what can be installed on top of Studio, read from packs/catalog/*.json.

A pack names everything it brings: files pinned to one revision with their size and sha256, Python packages, and the
licenses a person agrees to first. A wrong catalog is a bug in this app, so loading it raises.
"""

from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from ..provenance import LicenseClass

CATALOG_DIR = Path(__file__).with_name("catalog")
# Where this PC is: a pack that excludes this region is not listed at all.
REGION = "KR"
LICENSE_HOSTS = ("huggingface.co", "www.apache.org")
FILE_HOST = "huggingface.co"

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def _relative(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
        raise ValueError(f"{value!r} must be a relative path inside the pack")
    return value


class PackLicense(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    class_: LicenseClass = Field(alias="class")
    url: str
    sha256: Sha256  # of the text at `url`, the one a person agrees to
    summary_ko: str

    @field_validator("url")
    @classmethod
    def check_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.hostname not in LICENSE_HOSTS:
            raise ValueError(f"a license text comes from {LICENSE_HOSTS} over https, not {value!r}")
        return value


class PackFile(BaseModel):
    repo: Annotated[str, StringConstraints(pattern=r"^[\w.-]+/[\w.-]+$")]
    revision: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]  # a commit, so the file cannot change
    path: str
    dest: str  # relative to the pack's folder
    size: int = Field(gt=0)
    sha256: Sha256

    @field_validator("path", "dest")
    @classmethod
    def check_relative(cls, value: str) -> str:
        return _relative(value)

    @property
    def url(self) -> str:
        return f"https://{FILE_HOST}/{self.repo}/resolve/{self.revision}/{self.path}"


class Measured(BaseModel):
    vram_gb: int
    ram_gb: int
    disk_gb: int  # free disk an install needs
    os: str


class PackSpec(BaseModel):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]+$")]
    title: str
    feature: str
    version: str
    engine: Literal["python_sidecar", "comfy_models", "comfy_engine"]
    model_dir: str  # relative to the pack's folder
    licenses: Annotated[list[PackLicense], Field(min_length=1)]
    files: Annotated[list[PackFile], Field(min_length=1)]
    requirements: list[str] = Field(default_factory=list)
    python: str
    torch_index: str
    torch_packages: list[str] = Field(default_factory=list)
    tested: Measured
    gated: bool = False
    excluded_regions: list[str] = Field(default_factory=list)

    @field_validator("model_dir")
    @classmethod
    def check_model_dir(cls, value: str) -> str:
        return _relative(value)

    @model_validator(mode="after")
    def check_unique(self) -> "PackSpec":
        if len({f.dest for f in self.files}) != len(self.files):
            raise ValueError(f"pack {self.id}: two files share a dest")
        if len({lic.id for lic in self.licenses}) != len(self.licenses):
            raise ValueError(f"pack {self.id}: two licenses share an id")
        return self

    @property
    def download_size(self) -> int:
        return sum(f.size for f in self.files)


def load_catalog(region: str = REGION) -> dict[str, PackSpec]:
    """Every pack allowed in `region`, by id."""
    packs = {}
    for path in sorted(CATALOG_DIR.glob("*.json")):
        pack = PackSpec.model_validate_json(path.read_text(encoding="utf-8"))
        if region not in pack.excluded_regions:
            packs[pack.id] = pack
    return packs
