"""Prompts for full-page pictures, built from a page and the book's sheets.

Reference order and limits come from docs/plans/notes/studio-three-refs.md: two character sheets and one place fit 16 GB
at about 20 s a picture. A place reference also brings its camera and objects, so a place sheet is an empty scene.
"""

from dataclasses import dataclass

from .store.models import Page, Sheet

MAX_PEOPLE_REFS = 2
ORDINALS = ("first", "second", "third")
PAGE_RULES = "Full-page illustration. No text, no letters, no watermark."
KEEP_PEOPLE = "Keep each character's face, hair and clothing as in the references, in a natural new pose."
EMPTY_SCENE = "An empty scene with nobody in it and no loose objects."


@dataclass(frozen=True)
class PagePrompt:
    text: str
    refs: tuple[Sheet, ...]  # the sheets to send, in the order the text names them


def _by_name(sheets: list[Sheet], kind: str) -> dict[str, Sheet]:
    return {s.name: s for s in sheets if s.kind == kind}


def page_prompt(style: str, sheets: list[Sheet], page: Page) -> PagePrompt:
    """References first, then what only words can carry, then the scene and the book's style."""
    characters = _by_name(sheets, "character")
    props = _by_name(sheets, "prop")
    named = [characters[name] for name in page.people if name in characters]
    drawn = [s for s in named if s.asset_id][:MAX_PEOPLE_REFS]
    place = _by_name(sheets, "place").get(page.place or "")
    refs = [*drawn, *([place] if place is not None and place.asset_id else [])]

    lines = []
    for i, sheet in enumerate(drawn):
        lines.append(
            f"The {ORDINALS[i]} reference image shows the character design of {sheet.name}: {sheet.description}"
        )
    if drawn:
        lines.append(KEEP_PEOPLE)
    if refs and refs[-1] is place:
        lines.append(
            f"The {ORDINALS[len(drawn)]} reference image shows the place {place.name}: {place.description} "
            "Keep its structure and materials. Place the people and the camera as this scene says."
        )
    elif place is not None:
        lines.append(f"The place is {place.name}: {place.description}")
    elif page.place:
        lines.append(f"The place: {page.place}")
    lines.extend(f"{s.name}: {s.description}" for s in named if s not in drawn)
    lines.extend(f"{props[p].name}: {props[p].description}" if p in props else p for p in page.props)
    lines.append(page.image_prompt)
    lines.append(f"{style} {PAGE_RULES}".strip())
    return PagePrompt(" ".join(line.strip() for line in lines if line.strip()), tuple(refs))


def sheet_prompt(style: str, sheet: Sheet) -> str:
    """A place or prop picture. A place must be empty: whatever it holds comes back in every page that uses it."""
    extra = EMPTY_SCENE if sheet.kind == "place" else ""
    return " ".join(part for part in (sheet.description.strip(), extra, style.strip(), PAGE_RULES) if part)


# At CFG 1 a negative prompt does nothing, so these limits are stated in the prompt (2026-11-01 trial).
STAY_IN_PLACE = "Everyone stays in exactly the same place facing the same way. Nobody walks, leaves or turns around. "
STAY_IN_PLACE += "Only small natural movement."
KEEP_STYLE = "The painted style stays the same, gentle natural motion, static composition."


def clip_prompt(style: str, motion: str, still: bool) -> str:
    return " ".join(part for part in (motion, STAY_IN_PLACE if still else "", style, KEEP_STYLE) if part)
