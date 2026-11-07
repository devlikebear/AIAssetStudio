import hashlib

import pytest

from aiassetstudio.packs.catalog import load_catalog
from aiassetstudio.packs.consent import (
    ConsentRequired,
    LicenseChanged,
    accept,
    missing_consents,
    require_consent,
    verify_licenses,
)
from aiassetstudio.store.db import Database

TEXT = b"the license text"


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "studio.db")
    yield database
    database.close()


@pytest.fixture
def pack():
    spec = load_catalog()["speech-ko"]
    return spec.model_copy(update={"licenses": [spec.licenses[0].model_copy(update={"sha256": sha(TEXT)})]})


def sha(text: bytes) -> str:
    return hashlib.sha256(text).hexdigest()


def test_an_install_needs_every_license(db, pack):
    with pytest.raises(ConsentRequired) as e:
        require_consent(db, pack)
    assert e.value.missing == pack.licenses
    accept(db, pack, [pack.licenses[0].id])
    require_consent(db, pack)
    assert missing_consents(db, pack) == []


def test_accepting_twice_keeps_the_first_record(db, pack):
    accept(db, pack, ["apache-2.0"])
    first = db.list_consents(pack.id)
    accept(db, pack, ["apache-2.0"])
    assert db.list_consents(pack.id) == first


def test_a_new_version_or_text_needs_consent_again(db, pack):
    accept(db, pack, ["apache-2.0"])
    assert missing_consents(db, pack.model_copy(update={"version": "2.0.0"})) == pack.licenses
    other = pack.model_copy(update={"licenses": [pack.licenses[0].model_copy(update={"sha256": sha(b"new text")})]})
    assert missing_consents(db, other) == other.licenses


def test_accept_refuses_an_unknown_license(db, pack):
    with pytest.raises(KeyError):
        accept(db, pack, ["gpl"])
    assert db.list_consents(pack.id) == []


async def test_verify_returns_the_text():
    pack = load_catalog()["speech-ko"]
    pack = pack.model_copy(update={"licenses": [pack.licenses[0].model_copy(update={"sha256": sha(TEXT)})]})

    async def fetch(url):
        return TEXT

    assert await verify_licenses(pack, fetch) == {"apache-2.0": TEXT}


async def test_a_changed_text_stops_the_install(pack):
    async def fetch(url):
        return b"changed"

    with pytest.raises(LicenseChanged):
        await verify_licenses(pack, fetch)
