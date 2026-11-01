from aiassetstudio.book_prompts import MAX_PEOPLE_REFS, page_prompt, sheet_prompt
from aiassetstudio.store.models import Page, Sheet

STYLE = "Ink wash on paper."


def sheet(kind, name, description="a description.", asset_id="a1") -> Sheet:
    return Sheet(
        id=f"s-{name}", book_id="b", kind=kind, name=name, description=description, asset_id=asset_id, created_at="t"
    )


def page(**fields) -> Page:
    defaults = {
        "id": "p",
        "book_id": "b",
        "number": 1,
        "image_prompt": "A scene.",
        "created_at": "t",
        "updated_at": "t",
    }
    return Page(**(defaults | fields))


def test_people_and_place_become_references_in_order():
    sheets = [sheet("character", "Ada"), sheet("character", "Bo"), sheet("place", "Hall")]
    prompt = page_prompt(STYLE, sheets, page(people=["Bo", "Ada"], place="Hall"))
    assert [s.name for s in prompt.refs] == ["Bo", "Ada", "Hall"]
    assert "The first reference image shows the character design of Bo" in prompt.text
    assert "The second reference image shows the character design of Ada" in prompt.text
    assert "The third reference image shows the place Hall" in prompt.text


def test_extra_people_go_in_words():
    names = ["Ada", "Bo", "Cy"]
    prompt = page_prompt(STYLE, [sheet("character", n) for n in names], page(people=names))
    assert len(prompt.refs) == MAX_PEOPLE_REFS
    assert "Cy: a description." in prompt.text
    assert "reference image shows the character design of Cy" not in prompt.text


def test_sheet_without_a_picture_goes_in_words():
    sheets = [sheet("character", "Ada", asset_id=None), sheet("place", "Hall", asset_id=None)]
    prompt = page_prompt(STYLE, sheets, page(people=["Ada"], place="Hall"))
    assert prompt.refs == ()
    assert "Ada: a description." in prompt.text
    assert "The place is Hall: a description." in prompt.text
    assert "Keep each character" not in prompt.text


def test_place_reference_takes_the_next_ordinal_without_people():
    prompt = page_prompt(STYLE, [sheet("place", "Hall")], page(place="Hall"))
    assert "The first reference image shows the place Hall" in prompt.text


def test_plain_place_and_props():
    sheets = [sheet("prop", "Ribbon", "a thin white ribbon.")]
    prompt = page_prompt(STYLE, sheets, page(place="a dark barn", props=["Ribbon", "a small lamp"]))
    assert "The place: a dark barn" in prompt.text
    assert "Ribbon: a thin white ribbon." in prompt.text
    assert "a small lamp" in prompt.text


def test_scene_then_style_and_rules_come_last():
    prompt = page_prompt(STYLE, [], page())
    assert prompt.text == "A scene. Ink wash on paper. Full-page illustration. No text, no letters, no watermark."


def test_place_sheet_prompt_is_an_empty_scene():
    assert "nobody" in sheet_prompt(STYLE, sheet("place", "Hall"))
    assert "nobody" not in sheet_prompt(STYLE, sheet("prop", "Ribbon"))
