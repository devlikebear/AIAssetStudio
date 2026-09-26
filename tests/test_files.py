import pytest

from aiassetstudio.config import Settings
from aiassetstudio.store.files import asset_dir, db_path, from_rel, project_dir, to_rel, validate_slug


@pytest.mark.parametrize("slug", ["smoke", "lastlight", "a1", "my-game-2", "0day", "a" * 41])
def test_valid_slugs(slug):
    assert validate_slug(slug) == slug


@pytest.mark.parametrize("slug", ["", "a", "-lead", "Upper", "under_score", "space here", "a" * 42, "../x", "é-game"])
def test_invalid_slugs(slug):
    with pytest.raises(ValueError):
        validate_slug(slug)


def test_layout_and_relative_paths(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    assert db_path(settings) == tmp_path / "data" / "studio.db"
    assert project_dir(settings, "demo") == tmp_path / "data" / "projects" / "demo"

    d = asset_dir(settings, "demo", "0123456789ab")
    assert d.is_dir()
    assert d == tmp_path / "data" / "projects" / "demo" / "assets" / "0123456789ab"

    rel = to_rel(settings, d / "raw.png")
    assert rel == "projects/demo/assets/0123456789ab/raw.png"
    assert from_rel(settings, rel) == (d / "raw.png").resolve()


def test_rejects_bad_ids_and_escapes(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    with pytest.raises(ValueError):
        asset_dir(settings, "demo", "../../etc")
    with pytest.raises(ValueError):
        from_rel(settings, "../outside.png")
