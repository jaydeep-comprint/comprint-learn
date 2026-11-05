"""Pure rules of the teacher dashboard (spec 010): no database."""

import uuid
from datetime import UTC, date, datetime, timedelta

from app.models import ConceptStatus, KpStatus, RemediationState
from app.schemas.dashboard import ConceptStat
from app.services import dashboard as d
from app.services import frontier
from app.services.frontier import ConceptView, Content, KpView, RemediationView, StudentRows

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _kp(concept: uuid.UUID, **kw: object) -> KpView:
    return KpView(uuid.uuid4(), concept, "kp", "KP", gradable=True, **kw)  # type: ignore[arg-type]


def _view(status: frontier.Status, kps: list[KpView]) -> ConceptView:
    return ConceptView(uuid.uuid4(), status, kps)


# --- memory band ----------------------------------------------------------------------------------


def test_memory_band_boundaries() -> None:
    assert d.memory_band(0.9) == "strong"
    assert d.memory_band(0.8999) == "fading"
    assert d.memory_band(0.7) == "fading"
    assert d.memory_band(0.6999) == "weak"
    assert d.memory_band(None) == "none"


# --- heat states ----------------------------------------------------------------------------------


def test_heat_state_plain_states() -> None:
    c = uuid.uuid4()
    assert d.heat_state(None) == "locked"
    assert d.heat_state(_view("locked", [])) == "locked"
    assert d.heat_state(_view("ready", [_kp(c)])) == "ready"
    assert d.heat_state(_view("learned", [_kp(c, status=KpStatus.passed)])) == "learned"
    assert d.heat_state(_view("in_progress", [_kp(c, status=KpStatus.in_progress)])) == (
        "in_progress"
    )


def test_stuck_via_waiting_kp() -> None:
    c = uuid.uuid4()
    view = _view("in_progress", [_kp(c, status=KpStatus.failed, open=False)])
    assert d.heat_state(view) == "stuck"
    reason = d.stuck_reason(view)
    assert reason is not None and reason.kind == "waiting"
    assert d.stuck_label(reason, None) == "Waiting to retry"
    # A failed KP that has reopened is just in progress.
    assert d.heat_state(_view("in_progress", [_kp(c, status=KpStatus.failed, open=True)])) == (
        "in_progress"
    )


def test_stuck_via_open_remediation_beats_waiting() -> None:
    c, prereq = uuid.uuid4(), uuid.uuid4()
    kp = _kp(c, status=KpStatus.failed, open=False)
    kp.remediations = [RemediationView(uuid.uuid4(), kp.id, prereq, RemediationState.review_due)]
    view = _view("in_progress", [kp])
    assert d.heat_state(view) == "stuck"
    reason = d.stuck_reason(view)
    assert reason == d.Stuck("review_due", prereq)
    assert d.stuck_label(reason, "Ratios") == "Brushing up Ratios"
    assert d.stuck_label(d.Stuck("relearn", prereq), "Ratios") == "Relearning Ratios"


def _content(concepts: list[uuid.UUID], kps: list[KpView]) -> Content:
    return Content(concepts, kps, set())


def test_complete_but_not_promoted_counts_as_learned_for_itself_and_dependants() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    kp_a = KpView(uuid.uuid4(), a, "x", "X", gradable=True)
    kp_b = KpView(uuid.uuid4(), b, "y", "Y", gradable=True)
    prereqs = {b: [a]}
    passed = type("P", (), {})()
    passed.status, passed.fail_count, passed.reopen_at = KpStatus.passed, 0, None
    passed.passed_at, passed.failed_at = NOW - timedelta(hours=1), None
    rows = StudentRows(stored={a: ConceptStatus.in_progress}, progress={kp_a.id: passed})
    content = _content([a, b], [kp_a, kp_b])
    plain = frontier.build(content, rows, prereqs, NOW)
    assert plain.status(a) == "in_progress" and plain.status(b) == "locked"
    eff = frontier.effective(frontier.build(content, rows, prereqs, NOW), prereqs)
    assert eff.status(a) == "learned" and eff.status(b) == "ready"
    assert d.heat_state(eff.views[a]) == "learned"
    # done_at falls back to the KP pass when learned_at is null.
    assert frontier.done_at(eff, a) == NOW - timedelta(hours=1)
    # The stored rows are untouched.
    assert rows.stored == {a: ConceptStatus.in_progress}


# --- ranking --------------------------------------------------------------------------------------


def _stat(ref: str, fail: float | None, stuck: int = 0) -> ConceptStat:
    return ConceptStat(
        concept=ref,
        title=ref,
        chapter="c",
        tries=10,
        students_tried=3 if fail is not None else 2,
        fail_rate=fail,
        stuck_now=stuck,
        learned_pct=0,
    )


def test_rank_weakest_order() -> None:
    order = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4}
    stats = [
        _stat("a", None),
        _stat("b", 0.2),
        _stat("c", 0.5),
        _stat("d", 0.2, 2),
        _stat("e", 0.2),
    ]
    ranked = [s.concept for s in d.rank_weakest(stats, order)]
    # fail rate desc, then stuck now desc, then course order; unqualified last.
    assert ranked == ["c", "d", "b", "e", "a"]


# --- at-risk rules --------------------------------------------------------------------------------


def _codes(**kw: object) -> list[str]:
    base: dict[str, object] = {"enrolled_days": 30}
    base.update(kw)
    return [r.code for r in d.at_risk_rules(d.RiskInputs(**base))]  # type: ignore[arg-type]


def test_kp_fail_rate_threshold() -> None:
    assert _codes(kp_ended=5, kp_failed=1) == ["kp_fail_rate"]  # 20% of 5
    assert _codes(kp_ended=4, kp_failed=2) == []  # fewer than 5 tries
    assert _codes(kp_ended=10, kp_failed=1) == []  # exactly 10% doesn't fire
    reason = d.at_risk_rules(d.RiskInputs(kp_ended=12, kp_failed=3, enrolled_days=30))[0]
    assert reason.detail == "Failed 3 of 12 KP tries"


def test_negative_xp() -> None:
    reasons = d.at_risk_rules(d.RiskInputs(negative_xp=2, enrolled_days=30))
    assert [r.code for r in reasons] == ["negative_xp"]
    assert reasons[0].detail == "Lost XP for rushing (2×)"  # noqa: RUF001


def test_low_xp_rate_needs_30_minutes() -> None:
    assert _codes(active_seconds=30 * 60, net_xp=14) == ["low_xp_rate"]  # 0.47/min
    assert _codes(active_seconds=29 * 60, net_xp=0) == []
    assert _codes(active_seconds=30 * 60, net_xp=15) == []  # exactly 0.5
    reason = d.at_risk_rules(d.RiskInputs(active_seconds=3600, net_xp=18, enrolled_days=30))[0]
    assert reason.detail == "0.3 XP per active minute"


def test_falling_memory_needs_two_weak_prereq_cards() -> None:
    assert _codes(weak_prereqs=["Linear equations", "Ratios"]) == ["falling_memory"]
    assert _codes(weak_prereqs=["Ratios"]) == []
    reason = d.at_risk_rules(d.RiskInputs(weak_prereqs=["A", "B"], enrolled_days=30))[0]
    assert reason.detail == "Weak memory: A, B"


def test_overdue_and_inactive() -> None:
    reasons = d.at_risk_rules(
        d.RiskInputs(overdue=[("Pairs", date(2026, 11, 3))], enrolled_days=30)
    )
    assert [(r.code, r.detail) for r in reasons] == [
        ("overdue_assignment", "Overdue: Pairs (due 3 Nov)")
    ]
    assert _codes(active_recently=False) == ["inactive"]
    assert _codes(active_recently=False, enrolled_days=6) == []


# --- windows --------------------------------------------------------------------------------------


def test_window_bounds_at_ist_midnight() -> None:
    # 2026-11-05 12:00 UTC is 17:30 IST on 5 Nov; 7d starts at 00:00 IST on 30 Oct.
    start = d.window_start("7d", NOW)
    assert start == datetime(2026, 10, 29, 18, 30, tzinfo=UTC)
    assert d.window_start("30d", NOW) == datetime(2026, 10, 6, 18, 30, tzinfo=UTC)
    assert d.window_start("all", NOW) is None
    # Just after IST midnight the window moves by a day.
    late = datetime(2026, 11, 5, 18, 31, tzinfo=UTC)  # 00:01 IST on 6 Nov
    assert d.window_start("7d", late) == datetime(2026, 10, 30, 18, 30, tzinfo=UTC)


# --- misconception helpers ------------------------------------------------------------------------


def test_tagged_misconceptions_and_option_text() -> None:
    answer = {
        "misconceptions": {"b": "sign-flip"},
        "spec": {"steps": [{"answer": {"mcq": {"options": [{"id": "a", "misconception": "m2"}]}}}]},
    }
    assert d.tagged_misconceptions(answer) == {"sign-flip", "m2"}
    public = {"options": [{"id": "a", "text": "1"}, {"id": "b", "text": "-1"}]}
    assert d.option_text(public, "b", 0) == "-1"
    steps = {"steps": [{"prompt": "x"}, {"options": [{"id": "c", "text": "C"}]}]}
    assert d.option_text(steps, "c", 1) == "C"
    assert d.option_text(public, None, 0) is None


def test_per_10() -> None:
    assert d.per_10(3, 10) == 3.0
    assert d.per_10(0, 0) is None
