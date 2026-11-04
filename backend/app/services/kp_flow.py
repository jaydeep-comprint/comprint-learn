"""KP question flow (spec 005): sessions, pass/fail, reopening and remediation.

The top of this module is pure (no DB) so the rules are unit-testable; the DB services below
take an `OrgScope` and write only for students (staff previews write nothing).
"""

from collections.abc import Collection, Hashable, Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

Outcome = Literal["active", "passed", "failed"]

IST = ZoneInfo("Asia/Kolkata")  # fixed for the CBSE pilot; per-school timezones are out of scope
MAX_KP_QUESTIONS = 5
MAX_REVIEW_QUESTIONS = 5

# --- pure rules -----------------------------------------------------------------------------------


def kp_outcome(results: Sequence[bool]) -> Outcome:
    """Pass: the last 2 answers correct. Fail: the last 3 wrong, or 5 answers without passing."""
    if len(results) >= 2 and results[-1] and results[-2]:
        return "passed"
    if len(results) >= 3 and not any(results[-3:]):
        return "failed"
    if len(results) >= MAX_KP_QUESTIONS:
        return "failed"
    return "active"


def review_outcome(results: Sequence[bool]) -> Outcome:
    """Pass: >= 3 answers, at least 2 of the last 3 correct and the last one correct.
    Fail: the last 3 wrong, or 5 answers without passing."""
    if len(results) >= 3 and results[-1] and sum(results[-3:]) >= 2:
        return "passed"
    if len(results) >= 3 and not any(results[-3:]):
        return "failed"
    if len(results) >= MAX_REVIEW_QUESTIONS:
        return "failed"
    return "active"


def choose_next_item[K: Hashable](
    pool: Sequence[K],
    last_answered: Mapping[K, datetime],
    served: Collection[K],
    param_items: Collection[K],
) -> K | None:
    """The next item for a session; deterministic given the student's history.

    `pool` is in this student's shuffled order (the tie-break). Items not yet served in this
    session come first, preferring ones never answered for this KP, then the least recently
    answered. Once every item has been served, only param items (new numbers) may come again.
    """
    index = {k: i for i, k in enumerate(pool)}
    floor = datetime.min.replace(tzinfo=UTC)

    def key(k: K) -> tuple[bool, datetime, int]:
        when = last_answered.get(k)
        return (when is not None, when or floor, index[k])

    fresh = [k for k in pool if k not in served]
    if fresh:
        return min(fresh, key=key)
    repeatable = [k for k in pool if k in param_items]
    return min(repeatable, key=key) if repeatable else None


def is_open(
    *,
    failed: bool,
    reopen_at: datetime | None,
    unresolved_remediations: int,
    passed_other_concept_since_fail: bool,
    passed_review_since_fail: bool,
    now: datetime,
) -> bool:
    """May the student start this KP's questions now? (Only failed KPs ever wait.)

    A failed KP is open when every remediation it triggered is resolved and one of: the cooldown
    is over, a KP in a different concept was passed since, or a remediation review was passed since.
    """
    if not failed:
        return True
    if unresolved_remediations:
        return False
    return (
        (reopen_at is not None and now >= reopen_at)
        or passed_other_concept_since_fail
        or passed_review_since_fail
    )


def next_midnight_ist(now: datetime) -> datetime:
    """The next 00:00 in Asia/Kolkata after `now` (aware), in UTC."""
    local = now.astimezone(IST)
    midnight = datetime.combine(local.date() + timedelta(days=1), time(0), tzinfo=IST)
    return midnight.astimezone(UTC)
