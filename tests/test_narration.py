from aiassetstudio.narration import apply_terms
from aiassetstudio.store.models import Term


def terms(**pairs) -> list[Term]:
    return [Term(term=k, spoken=v) for k, v in pairs.items()]


def test_a_term_is_written_as_it_is_said():
    assert apply_terms("남 영감이 왔다", terms(**{"남 영감": "남영감"})) == "남영감이 왔다"


def test_no_terms_leaves_the_text():
    assert apply_terms("그대로", []) == "그대로"


def test_the_longest_term_wins():
    assert apply_terms("강 선생님", terms(**{"강": "A", "강 선생님": "강선생님"})) == "강선생님"


def test_one_term_does_not_rewrite_another():
    assert apply_terms("가 나", terms(가="나", 나="다")) == "나 다"


def test_a_term_with_regex_characters_is_plain_text():
    assert apply_terms("a.b axb", terms(**{"a.b": "c"})) == "c axb"
