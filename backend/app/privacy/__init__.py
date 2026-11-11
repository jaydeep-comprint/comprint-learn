"""The AI-tutor consent notice (spec 014): one source for the API, the printed form and /privacy.

`notice.md` has YAML front matter (`version`, `title`) and two H2 sections: the notice (`body_md`,
printed on the form) and "What this app stores about you" (`stores_md`). Bumping `version` is how a
reviewed text ships; consent recorded on an older version stays valid.
"""

import functools
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

NOTICE_PATH = Path(__file__).with_name("notice.md")
PLACEHOLDER = re.compile(r"\[[A-Z][A-Z ]+\]")


@dataclass(frozen=True)
class Notice:
    version: str
    title: str
    body_md: str
    stores_md: str


def parse(text: str) -> Notice:
    _, front, rest = text.split("---\n", 2)
    meta = yaml.safe_load(front)
    h2 = [m.start() for m in re.finditer(r"^## ", rest, flags=re.MULTILINE)]
    if len(h2) < 2:
        raise ValueError("notice.md needs two H2 sections")
    return Notice(
        version=str(meta["version"]),
        title=str(meta["title"]),
        body_md=rest[: h2[1]].strip(),
        stores_md=rest[h2[1] :].strip(),
    )


@functools.cache
def notice() -> Notice:
    return parse(NOTICE_PATH.read_text(encoding="utf-8"))


def placeholders() -> list[str]:
    """Placeholders still to fill before the pilot (`[OPERATOR NAME]`, `[CONTACT]`)."""
    n = notice()
    return sorted(set(PLACEHOLDER.findall(n.body_md + n.stores_md)))


NOTICE_VERSION = notice().version
