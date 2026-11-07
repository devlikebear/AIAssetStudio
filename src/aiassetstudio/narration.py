"""Narration of a book: one narrator reads each page's text. Multi-voice narration was dropped after a person listened
to the spike (T2.A.1), so the voice is fixed here rather than set per book."""

import re
from collections.abc import Iterable

from .store.models import Term

SPEECH_PACK = "speech-ko"
SPEECH_MODEL = "Qwen3-TTS-12Hz-1.7B-CustomVoice"
SPEECH_MODELS = {"tts": SPEECH_MODEL}
SPEAKER = "Sohee"  # the only Korean preset
LANGUAGE = "Korean"
INSTRUCT = "Read slowly and calmly in a low voice, like an audiobook narrator telling a quiet sad story."


def apply_terms(text: str, terms: Iterable[Term]) -> str:
    """The text as the narrator should read it: each term written the way it must be said, longest term first and in
    one pass, so one term never rewrites what another put there. Subtitles and the PDF keep the page's own text."""
    spoken = {t.term: t.spoken for t in terms}
    if not spoken:
        return text
    pattern = "|".join(re.escape(term) for term in sorted(spoken, key=len, reverse=True))
    return re.sub(pattern, lambda match: spoken[match.group()], text)
