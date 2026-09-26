"""On-disk layout under data_dir. The DB stores file paths relative to data_dir.

data/studio.db
data/logs/
data/projects/<slug>/assets/<asset_id>/{raw,processed,preview}.png
data/projects/<slug>/reference/<content hash>.png
"""

import re
from pathlib import Path

from ..config import Settings

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,40}$"
IMAGE_FILES = ("raw", "processed", "preview")  # saved as <name>.png

_SLUG_RE = re.compile(SLUG_PATTERN)
_ASSET_ID_RE = re.compile(r"[0-9a-f]{12}")


def validate_slug(slug: str) -> str:
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
        raise ValueError(f"invalid project slug {slug!r}: 2-41 chars of a-z, 0-9 and '-', not starting with '-'")
    return slug


def db_path(settings: Settings) -> Path:
    return settings.data_dir / "studio.db"


def logs_dir(settings: Settings) -> Path:
    return settings.data_dir / "logs"


def project_dir(settings: Settings, slug: str) -> Path:
    return settings.data_dir / "projects" / validate_slug(slug)


def asset_dir(settings: Settings, slug: str, asset_id: str) -> Path:
    """Directory for one asset's files; created if missing."""
    if not _ASSET_ID_RE.fullmatch(asset_id):
        raise ValueError(f"invalid asset id {asset_id!r}")
    path = project_dir(settings, slug) / "assets" / asset_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def reference_dir(settings: Settings, slug: str) -> Path:
    """Directory for a project's reference image copies; created if missing."""
    path = project_dir(settings, slug) / "reference"
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_stem(name: str) -> str:
    """Lowercase `name` and keep only a-z, 0-9, '_' and '-' (may return "")."""
    return re.sub(r"[^a-z0-9_-]", "", name.lower())


def unique_path(directory: Path, stem: str, ext: str) -> Path:
    """`directory/stem+ext`, or `stem_2`, `stem_3`, ... if taken. Existing files are never overwritten."""
    return directory / f"{unique_stem(directory, stem, [ext])}{ext}"


def unique_stem(directory: Path, stem: str, exts: list[str]) -> str:
    """`stem`, or `stem_2`, `stem_3`, ...: the first for which no `directory/<stem><ext>` exists for any of `exts`,
    so files exported together (a song's WAV and OGG) keep one name."""
    candidate, n = stem, 2
    while any((directory / f"{candidate}{ext}").exists() for ext in exts):
        candidate, n = f"{stem}_{n}", n + 1
    return candidate


def to_rel(settings: Settings, path: Path) -> str:
    return Path(path).resolve().relative_to(settings.data_dir.resolve()).as_posix()


def from_rel(settings: Settings, rel: str) -> Path:
    root = settings.data_dir.resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path escapes the data directory: {rel!r}")
    return path
