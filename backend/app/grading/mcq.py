"""Multiple choice: clients see positional option ids, never authored ones."""

from dataclasses import dataclass
from typing import Any

from app.schemas.content import OptionPublic


@dataclass(frozen=True)
class ShownOptions:
    """An item's options in the order this user sees them.

    Clients never see authored option ids (they would give the answer away: authors tend to put
    the correct option first). They get positional ids "1".."n" in shown order instead; the server
    maps them back. Attempts store authored ids.
    """

    authored: list[OptionPublic]

    def public(self) -> list[OptionPublic]:
        return [OptionPublic(id=str(i + 1), text=o.text) for i, o in enumerate(self.authored)]

    def to_authored(self, client_id: str) -> str | None:
        if not (client_id.isascii() and client_id.isdigit()) or not 1 <= int(client_id) <= len(
            self.authored
        ):
            return None
        return self.authored[int(client_id) - 1].id

    def to_client(self, authored_id: str | None) -> str:
        ids = [o.id for o in self.authored]
        return str(ids.index(authored_id) + 1) if authored_id in ids else ""


class InvalidOptionError(ValueError):
    """The response isn't one of the shown positional ids (→ 422 `invalid_option`)."""


@dataclass(frozen=True)
class McqGrade:
    correct: bool
    display_answer: str  # the correct option's positional id
    chosen: str  # authored id
    misconception: str | None  # the chosen option's misconception slug, if tagged


def grade_mcq(answer: dict[str, Any], shown: ShownOptions, response: str) -> McqGrade:
    chosen = shown.to_authored(response.strip())
    if chosen is None:
        raise InvalidOptionError(response)
    correct_id = answer.get("correct")
    return McqGrade(
        correct=chosen == correct_id,
        display_answer=shown.to_client(correct_id),
        chosen=chosen,
        misconception=(answer.get("misconceptions") or {}).get(chosen),
    )
