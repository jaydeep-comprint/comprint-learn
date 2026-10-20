import re

import pytest

from app.core.usernames import SUFFIX_DIGITS, username_base, username_candidate


@pytest.mark.parametrize(
    ("name", "base"),
    [
        ("Aarav S.", "aarav"),
        ("  priya   K ", "priya"),
        ("O'Brien", "obrien"),
        ("Jean-Luc", "jeanluc"),
        ("Bartholomewsky Jr", "bartholomews"),
        ("आरव शर्मा", "student"),
        ("123", "student"),
        ("Zoë", "zo"),
        ("", "student"),
    ],
)
def test_username_base(name: str, base: str) -> None:
    assert username_base(name) == base


def test_candidate_shape() -> None:
    for digits in (2, 3, 4):
        u = username_candidate("aarav", digits)
        assert re.fullmatch(rf"aarav\d{{{digits}}}", u)


def test_candidates_vary() -> None:
    assert len({username_candidate("x", 4) for _ in range(50)}) > 10


def test_suffix_schedule_escalates_and_allows_five_tries() -> None:
    assert len(SUFFIX_DIGITS) == 5
    assert list(SUFFIX_DIGITS) == sorted(SUFFIX_DIGITS)
    assert SUFFIX_DIGITS[0] == 2 and SUFFIX_DIGITS[-1] == 4
