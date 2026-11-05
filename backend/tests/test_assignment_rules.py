"""Pure assignment rules (spec 010): statuses, the Focus path and its Next step. No database."""

import uuid
from datetime import UTC, date, datetime

from app.services.assignments import Step, TargetState, assignment_status, focus_path, next_step

CREATED = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
DUE = date(2026, 11, 8)


def _status(targets: list[TargetState], today: date = date(2026, 11, 5), started: bool = False):  # type: ignore[no-untyped-def]
    return assignment_status(
        targets, path_started=started, created_at=CREATED, due_date=DUE, today=today
    )


def _learned(at: datetime) -> TargetState:
    return TargetState(learned=True, started=True, done_at=at)


NOT = TargetState(learned=False, started=False, done_at=None)
STARTED = TargetState(learned=False, started=True, done_at=None)


def test_done_early_on_time_late() -> None:
    assert _status([_learned(datetime(2026, 10, 30, tzinfo=UTC))])[0] == "done_early"
    on_time = _learned(datetime(2026, 11, 8, 18, 0, tzinfo=UTC))  # 23:30 IST on the due date
    assert _status([on_time]) == ("done_on_time", on_time.done_at)
    late = _learned(datetime(2026, 11, 8, 18, 31, tzinfo=UTC))  # 00:01 IST on 9 Nov
    assert _status([late], today=date(2026, 11, 10))[0] == "done_late"
    # done_at is the latest learned_at among the targets.
    early, later = _learned(datetime(2026, 10, 30, tzinfo=UTC)), _learned(CREATED.replace(day=3))
    assert _status([early, later]) == ("done_on_time", later.done_at)


def test_overdue_in_progress_not_started() -> None:
    assert _status([NOT], today=date(2026, 11, 9))[0] == "overdue"
    assert _status([NOT], today=DUE)[0] == "not_started"  # due today: not overdue yet
    assert _status([STARTED])[0] == "in_progress"
    assert _status([NOT], started=True)[0] == "in_progress"  # a path concept is in progress
    assert _status([_learned(CREATED), NOT])[0] == "in_progress"


def test_relearned_target_undoes_done() -> None:
    # After a failed review the target is in progress again: not done.
    assert _status([_learned(CREATED.replace(day=2)), STARTED])[0] == "in_progress"


def test_focus_path_order_and_learned_ancestors_dropped() -> None:
    # Graph: other/x -> a -> b -> target; c -> target; a is learned.
    order = {"other/x": (0, 0), "a": (1, 0), "c": (1, 1), "b": (1, 2), "target": (1, 3)}
    prereqs = {"target": ["b", "c"], "b": ["a"], "a": ["other/x"]}
    learned = {"a"}
    path = focus_path(["target"], prereqs, lambda c: c in learned, lambda c: order[c])
    # Walks through the learned `a` to the cross-course `other/x`; prerequisites first.
    assert path == ["other/x", "c", "b", "target"]
    assert focus_path(["a"], prereqs, lambda c: True, lambda c: order[c]) == []


def _step(status: str, waiting: bool = False, brush: uuid.UUID | None = None) -> Step:
    return Step(uuid.uuid4(), status, waiting, brush)  # type: ignore[arg-type]


def test_next_step_rules() -> None:
    ready = _step("ready")
    progress = _step("in_progress")
    assert next_step([ready, progress]) == progress  # in progress beats ready
    waiting = _step("stuck", waiting=True)
    assert next_step([waiting, ready]) == ready  # waiting skipped
    brush = _step("stuck", brush=uuid.uuid4())
    assert next_step([brush, ready]) == brush  # a due brush-up is the next step
    assert next_step([waiting, _step("locked")]) is None
