import math
import re

from app.core.passwords import WORDS, temp_password

PATTERN = re.compile(r"([a-z]+)-([a-z]+)-(\d{2})")


def test_shape_and_charset() -> None:
    for _ in range(200):
        pw = temp_password()
        m = PATTERN.fullmatch(pw)
        assert m, pw
        assert m.group(1) in WORDS and m.group(2) in WORDS
        assert 8 <= len(pw) <= 72


def test_wordlist_is_clean_and_large_enough() -> None:
    assert len(set(WORDS)) == len(WORDS)
    assert all(re.fullmatch(r"[a-z]{3,8}", w) for w in WORDS)
    # Entropy floor: 2 words + 2 digits.
    assert math.log2(len(WORDS) ** 2 * 100) >= 20


def test_passwords_vary() -> None:
    assert len({temp_password() for _ in range(100)}) > 95
