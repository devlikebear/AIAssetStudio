import json

import pytest
from pydantic import ValidationError

from aiassetstudio.packs import catalog
from aiassetstudio.packs.catalog import PackSpec, load_catalog


def spec(**changes) -> dict:
    pack = json.loads((catalog.CATALOG_DIR / "speech-ko.json").read_text(encoding="utf-8"))
    return pack | changes


def test_catalog_lists_the_speech_pack():
    pack = load_catalog()["speech-ko"]
    assert pack.licenses[0].class_ == "open"
    assert pack.download_size > 4 * 2**30
    assert all(f.url.startswith("https://huggingface.co/Qwen/") for f in pack.files)
    assert {f.path for f in pack.files} >= {"model.safetensors", "speech_tokenizer/model.safetensors"}
    assert all(f.dest.startswith(pack.model_dir) for f in pack.files)


@pytest.mark.parametrize(
    "changes",
    [
        {"licenses": []},
        {"id": "Bad Id"},
        {"engine": "magic"},
    ],
)
def test_a_wrong_pack_does_not_load(changes):
    with pytest.raises(ValidationError):
        PackSpec.model_validate(spec(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"dest": "../outside.bin"},
        {"dest": "C:/outside.bin"},
        {"revision": "main"},
        {"repo": "https://evil.example/x"},
        {"sha256": "abc"},
    ],
)
def test_a_wrong_file_does_not_load(changes):
    pack = spec()
    pack["files"][0] |= changes
    with pytest.raises(ValidationError):
        PackSpec.model_validate(pack)


def test_a_license_comes_from_a_known_host():
    pack = spec()
    pack["licenses"][0]["url"] = "https://evil.example/LICENSE"
    with pytest.raises(ValidationError):
        PackSpec.model_validate(pack)


def test_two_files_cannot_share_a_dest():
    pack = spec()
    pack["files"].append(pack["files"][0])
    with pytest.raises(ValidationError):
        PackSpec.model_validate(pack)


def test_a_pack_that_excludes_the_region_is_not_listed(tmp_path, monkeypatch):
    (tmp_path / "open.json").write_text(json.dumps(spec()), encoding="utf-8")
    (tmp_path / "closed.json").write_text(json.dumps(spec(id="closed", excluded_regions=["KR"])), encoding="utf-8")
    monkeypatch.setattr(catalog, "CATALOG_DIR", tmp_path)
    assert list(load_catalog()) == ["speech-ko"]
    assert sorted(load_catalog("US")) == ["closed", "speech-ko"]
