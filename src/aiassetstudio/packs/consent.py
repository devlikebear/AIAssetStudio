"""License consent: an install needs a person's agreement to the exact text of every license of the pack.

Only the gallery records consent (api/app.py); an agent or the CLI can start an install but cannot agree. This stops an
agent from agreeing by mistake. It is not a security boundary against another program on this PC.
"""

import hashlib
from collections.abc import Awaitable, Callable

from ..store.db import Database
from .catalog import PackLicense, PackSpec


class ConsentRequired(Exception):
    def __init__(self, pack: PackSpec, missing: list[PackLicense]):
        super().__init__(f"pack {pack.id} needs a person's consent to: {', '.join(lic.name for lic in missing)}")
        self.pack = pack
        self.missing = missing


class LicenseChanged(Exception):
    """The license text online is not the one the catalog holds, so what a person agreed to no longer applies."""

    def __init__(self, pack: PackSpec, license_: PackLicense):
        super().__init__(f"the license text of pack {pack.id} changed: {license_.name} ({license_.url})")
        self.license = license_


def missing_consents(db: Database, pack: PackSpec) -> list[PackLicense]:
    agreed = {(c.pack_version, c.license_id, c.license_sha256) for c in db.list_consents(pack.id)}
    return [lic for lic in pack.licenses if (pack.version, lic.id, lic.sha256) not in agreed]


def require_consent(db: Database, pack: PackSpec) -> None:
    if missing := missing_consents(db, pack):
        raise ConsentRequired(pack, missing)


def accept(db: Database, pack: PackSpec, license_ids: list[str]) -> None:
    """Record agreement to the named licenses of the pack as they are in the catalog now."""
    by_id = {lic.id: lic for lic in pack.licenses}
    if unknown := [i for i in license_ids if i not in by_id]:
        raise KeyError(f"pack {pack.id} has no license {unknown}")
    for license_id in license_ids:
        db.add_consent(pack.id, pack.version, license_id, by_id[license_id].sha256)


async def verify_licenses(pack: PackSpec, fetch: Callable[[str], Awaitable[bytes]]) -> dict[str, bytes]:
    """The text of each license, as fetched now. Raises LicenseChanged if one differs from what was agreed to."""
    texts = {}
    for lic in pack.licenses:
        text = await fetch(lic.url)
        if hashlib.sha256(text).hexdigest() != lic.sha256:
            raise LicenseChanged(pack, lic)
        texts[lic.id] = text
    return texts
