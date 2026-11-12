"""The consent notice (spec 014) parses into version, title and two sections."""

import warnings

import pytest

from app import privacy


def test_notice_parses() -> None:
    n = privacy.notice()
    assert n.version == privacy.NOTICE_VERSION == "2026-11-v1"
    assert n.title
    assert n.body_md.startswith("## About the AI tutor")
    assert n.stores_md.startswith("## What this app stores about you")
    assert "DeepSeek" in n.body_md and "China" in n.body_md and "180 days" in n.body_md


def test_parse_needs_two_sections() -> None:
    with pytest.raises(ValueError):
        privacy.parse('---\nversion: "x"\ntitle: "t"\n---\n## Only one\n')


def test_placeholders_are_listed_not_failed() -> None:
    """Replacing them is a pilot-readiness item, not a `make check` failure."""
    left = privacy.placeholders()
    if left:
        warnings.warn(f"notice.md placeholders to fill: {', '.join(left)}", stacklevel=1)
    assert set(left) <= {"[OPERATOR NAME]", "[CONTACT]"}
