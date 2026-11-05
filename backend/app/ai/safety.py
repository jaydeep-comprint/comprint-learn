"""Distress keywords and personal-data scrubbing for student text (spec 009). Pure."""

import re

SAFETY_KEYWORDS = (
    "kill myself",
    "killing myself",
    "suicide",
    "suicidal",
    "hurt myself",
    "hurting myself",
    "harm myself",
    "self harm",
    "self-harm",
    "cut myself",
    "want to die",
    "end my life",
    "abuse",
    "abused",
    "abusing me",
    "bully",
    "bullies",
    "bullied",
    "bullying",
    "beats me",
    "hits me",
    "touches me",
)

_KEYWORDS = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in SAFETY_KEYWORDS) + r")\b", re.IGNORECASE
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# An Indian mobile number not part of a longer digit run.
_MOBILE = re.compile(r"(?<![\d+])(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)")
REMOVED = "[removed]"


def is_distress(text: str) -> bool:
    return _KEYWORDS.search(text) is not None


def scrub_pii(text: str) -> str:
    """Emails and Indian mobile numbers → "[removed]" (before sending and storing)."""
    return _MOBILE.sub(REMOVED, _EMAIL.sub(REMOVED, text))
