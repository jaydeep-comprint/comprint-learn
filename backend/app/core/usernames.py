"""Student usernames: ASCII letters of the display name's first word + random digits."""

import re
import secrets

MAX_BASE_LEN = 12
FALLBACK_BASE = "student"
# Suffix lengths tried in order: 2 digits, then 3, then 4 when the shorter ones keep colliding.
SUFFIX_DIGITS = (2, 2, 3, 3, 4)

_NON_ASCII_LETTERS = re.compile(r"[^a-z]")


def username_base(display_name: str) -> str:
    """`"Aarav S."` → `"aarav"`; no ASCII letters (e.g. Devanagari) → `"student"`."""
    words = display_name.split()
    first = words[0].lower() if words else ""
    base = _NON_ASCII_LETTERS.sub("", first)[:MAX_BASE_LEN]
    return base or FALLBACK_BASE


def username_candidate(base: str, digits: int) -> str:
    """`base` + `digits` random digits (first digit may be 0, so `aarav07` is valid)."""
    return base + "".join(secrets.choice("0123456789") for _ in range(digits))
