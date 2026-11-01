from aiassetstudio.comfy.graphs import ACE_MODELS, QWEN_BOOK_MODELS, QWEN_MODELS, VIGGLE_LORA, YUE2_MODELS
from aiassetstudio.provenance import license_names, license_records, worst_class


def test_every_model_file_has_a_record():
    records = license_records(QWEN_MODELS)
    assert {r["file"] for r in records} == set(QWEN_MODELS.values())
    assert all(r["name"] != "unlisted model" for r in records)


def test_book_pictures_need_no_lora_of_unread_terms():
    records = license_records(QWEN_BOOK_MODELS)
    assert all(r["name"] != "unlisted model" for r in records)
    assert {r["class"] for r in records} == {"research_only"}


def test_lists_of_files_are_flattened():
    assert len(license_records(ACE_MODELS)) == 4
    assert {r["class"] for r in license_records(ACE_MODELS)} == {"open"}


def test_worst_class():
    assert worst_class(license_records(QWEN_MODELS)) == "research_only"
    assert worst_class(license_records(YUE2_MODELS)) == "community"
    assert worst_class(license_records(ACE_MODELS) + license_records(YUE2_MODELS)) == "community"


def test_nothing_on_record_is_unknown():
    assert worst_class([]) == "unknown"
    assert license_records({"unet": "something_else.safetensors"})[0]["class"] == "unknown"


def test_unread_license_stays_unknown():
    assert [r["class"] for r in license_records({"lora": VIGGLE_LORA})] == ["unknown"]


def test_names_are_unique_in_order():
    names = license_names(license_records(QWEN_MODELS))
    assert names == ["Qwen-Image-2.1 (Qwen Research License)", "Viggle Turbo LoRA (not verified)"]
