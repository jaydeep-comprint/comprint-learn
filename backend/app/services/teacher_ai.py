"""Teacher AI summaries (spec 011): facts from 010's snapshot, caps, the model call and rendering.

Every POST is **reserve, call, store** (009's pattern): Tx 1 takes a per-school advisory lock,
checks caps, cooldown and busy, and inserts a `pending` row; the model call runs with no
transaction open; Tx 2 stores the guarded output and tokens. Stored text keeps `{Sn}` tokens; names
are filled in on read from the class's current roster. Logs carry ids, status and tokens only.
"""

import logging
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, text, update

from app.ai import teacher_facts as tf
from app.ai import teacher_limits as lim
from app.ai.teacher_client import TeacherAIUnavailable, TeacherClient
from app.ai.teacher_facts import TOKEN, FactSet
from app.ai.teacher_schema import ModelOutput
from app.ai.teacher_turn import SummaryResult, run_summary
from app.api.deps import OrgScope
from app.core.config import get_settings
from app.core.errors import ApiProblem
from app.models import AppUser, RemediationState, StudyActivity, TeacherSummary, UserStatus
from app.models import TeacherSummaryKind as Kind
from app.models import TeacherSummaryStatus as Status
from app.schemas.dashboard import Window
from app.schemas.teacher_ai import (
    AssignPrefill,
    Blocked,
    ClaimOut,
    FactLink,
    FactOut,
    NoteOut,
    ResourceOut,
    StudentRef,
    Summary,
    SummaryState,
)
from app.services import class_view, dashboard, kp_flow
from app.services.class_view import ClassCtx

log = logging.getLogger(__name__)

USABLE = (Status.ok, Status.partial)
COUNTED = (Status.pending, Status.ok, Status.partial, Status.failed)
GONE = "a student no longer in this class"
NOT_ENOUGH = "Not enough activity yet for a useful summary. Check back after a few lessons."


def _ist_day(now: datetime) -> date:
    return now.astimezone(kp_flow.IST).date()


# --- facts ----------------------------------------------------------------------------------------


def _label(kind: str, title: str | None) -> str:
    if kind == "review_due":
        return f"brushing up '{title}'"
    if kind == "relearn":
        return f"relearning '{title}'"
    return "waiting to retry"


async def class_input(scope: OrgScope, ctx: ClassCtx, window: Window) -> tf.ClassInput:
    snap = await dashboard.class_snapshot(scope, ctx, window)
    sids = ctx.student_ids
    rems = await dashboard._remediations_since(scope, sids, ctx.concepts, snap.since)
    weakest = snap.weakest
    weak_ids = [ctx.graph.by_ref[s.concept] for s in weakest]
    kp_ids = {t[2] for t in snap.tries if t[1] in weak_ids} | {r.kp_id for r in rems}
    kps = await dashboard.kp_info(scope, kp_ids)

    per_kp: dict[uuid.UUID, Counter[str]] = defaultdict(Counter)
    for _sid, _cid, kp, is_failed, n in snap.tries:
        per_kp[kp]["ended"] += n
        per_kp[kp]["failed"] += n if is_failed else 0
    weak = []
    for stat, cid in zip(weakest, weak_ids, strict=True):
        failed = sum(n for _s, c, _k, f, n in snap.tries if c == cid and f)
        kp_rows = tuple(
            tf.KpTries(kps[k].slug, kps[k].title, per_kp[k]["failed"], per_kp[k]["ended"])
            for k in dict.fromkeys(t[2] for t in snap.tries if t[1] == cid)
            if k in kps
        )
        weak.append(
            tf.WeakConcept(
                ref=stat.concept,
                title=stat.title,
                chapter=stat.chapter,
                tries=stat.tries,
                failed=failed,
                students_tried=stat.students_tried,
                stuck_now=stat.stuck_now,
                learned_pct=stat.learned_pct,
                kps=kp_rows,
            )
        )

    choosers: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for sid, iid, mid, _opt, _step in snap.chosen:
        if iid in snap.items:
            choosers[mid].add(sid)
    miscs = [
        tf.MisconceptionIn(
            id=m.id,
            title=m.title,
            concept_ref=m.concept,
            concept_title=m.concept_title,
            chosen=m.chosen,
            offered=m.offered,
            students=tuple(sorted(choosers[m.id])),
        )
        for m in snap.top_misconceptions
    ]

    # Every open remediation of a stuck concept counts, one per (student, prerequisite): a KP's
    # 2nd fail opens one per key prerequisite. Within a pair, review_due wins over relearn.
    now_groups: dict[tuple[uuid.UUID, uuid.UUID], dict[str, list[uuid.UUID]]] = {}
    for s in ctx.students:
        for cid in ctx.concepts:
            view = dashboard._view(ctx, s.id, cid)
            if view is None or dashboard.heat_state(view) != "stuck":
                continue
            per_prereq: dict[uuid.UUID, str] = {}
            for kp_view in view.kps:
                for rem in kp_view.remediations:
                    p = rem.prereq_concept_id
                    if p not in ctx.graph.nodes:
                        continue
                    if per_prereq.get(p) != "review_due":
                        per_prereq[p] = rem.state.value
            for p, kind in per_prereq.items():
                if kind not in ("review_due", "relearn"):
                    continue
                group = now_groups.setdefault((p, cid), {"review_due": [], "relearn": []})
                group[kind].append(s.id)
    causes_now = [
        tf.CauseNow(
            prereq_ref=ctx.ref(p),
            prereq_title=ctx.title(p),
            concept_ref=ctx.ref(c),
            concept_title=ctx.title(c),
            review_due=tuple(g["review_due"]),
            relearn=tuple(g["relearn"]),
        )
        for (p, c), g in now_groups.items()
    ]

    window_groups: dict[tuple[uuid.UUID, uuid.UUID], dict[uuid.UUID, bool]] = {}
    for r in rems:
        if r.kp_id not in kps or r.prereq_id not in ctx.graph.nodes:
            continue
        seen = window_groups.setdefault((r.kp_id, r.prereq_id), {})
        seen[r.student_id] = seen.get(r.student_id, False) or (r.state == RemediationState.resolved)
    causes_window = []
    for (kp, prereq), students in window_groups.items():
        info = kps[kp]
        causes_window.append(
            tf.CauseWindow(
                kp_slug=info.slug,
                kp_title=info.title,
                concept_ref=ctx.ref(info.concept_id),
                concept_title=ctx.title(info.concept_id),
                prereq_ref=ctx.ref(prereq),
                prereq_title=ctx.title(prereq),
                students=tuple(sorted(students)),
                resolved=sum(students.values()),
            )
        )

    at_risk = [
        (row.student_id, [r.detail for r in row.reasons])
        for row in dashboard._at_risk_rows(ctx, snap.reasons)
    ]
    hint_use = snap.hint_use
    assert hint_use is not None
    picked = list(snap.assignments_due)
    for a in snap.overdue:
        if a.content_available and a not in picked:
            picked.append(a)
    share = snap.practice_share
    return tf.ClassInput(
        window=window,
        students_in_scope=len(sids),
        learn_seconds=share.learn_seconds,
        practice_seconds=share.practice_seconds,
        weak_concepts=weak,
        misconceptions=miscs,
        causes_now=causes_now,
        causes_window=causes_window,
        at_risk=at_risk,
        hints_per_10=hint_use.hints_per_10,
        hint_top=[(t.student_id, t.hints_per_10 or 0.0) for t in hint_use.top],
        assignments=[
            tf.AssignmentIn(
                id=a.id,
                title=a.title,
                due=a.due_date,
                done=a.counts.done + a.counts.done_late + a.counts.already_learned,
                total=a.counts.total,
                overdue=a.counts.overdue,
                not_started=a.counts.not_started,
            )
            for a in picked[: lim.MAX_ASSIGNMENTS]
        ],
    )


async def student_input(scope: OrgScope, ctx: ClassCtx) -> tf.StudentInput:
    """`ctx` is loaded for one student."""
    snap = await dashboard.student_snapshot(scope, ctx)
    sid = snap.student.id
    concepts = ctx.concepts
    chosen = await dashboard._chosen(scope, [sid], concepts, snap.since)
    items = await dashboard._items(scope, concepts)
    miscs = {m.id: m for m in await dashboard._misconception_rows(scope, ctx)}
    rems = await dashboard._remediations_since(scope, [sid], concepts, snap.since)

    stuck: list[tf.StuckIn] = []
    in_progress: list[tuple[str, str]] = []
    weak_mem: list[tuple[float, str, str]] = []
    fading_mem: list[tuple[float, str, str]] = []
    open_rems: list[tuple[uuid.UUID, uuid.UUID, RemediationState]] = []
    kp_concept: dict[uuid.UUID, uuid.UUID] = {}
    if ctx.course is not None:
        pairs, front, cards = await dashboard.outline_states(scope, ctx)
        kp_concept = front.kp_concept
        for cid, _anchor in pairs:
            view = front.views[cid]
            heat = dashboard.heat_state(view)
            ref, title = ctx.ref(cid), ctx.title(cid)
            if heat == "stuck":
                reason = dashboard.stuck_reason(view)
                assert reason is not None
                prereq_title = None if reason.prereq is None else ctx.title(reason.prereq)
                stuck.append(tf.StuckIn(ref, title, _label(reason.kind, prereq_title)))
            elif heat == "in_progress":
                in_progress.append((ref, title))
            elif cid in ctx.concept_set:
                band, retr = dashboard._band(heat, cards.get((sid, cid)), snap.now)
                if band == "weak" and retr is not None:
                    weak_mem.append((retr, ref, title))
                elif band == "fading" and retr is not None:
                    fading_mem.append((retr, ref, title))
        open_rems = [
            (r.kp_id, r.prereq_concept_id, r.state)
            for r in front.remediations
            if kp_concept.get(r.kp_id) in ctx.concept_set
        ]

    kp_ids = {t[2] for t in snap.tries} | {r.kp_id for r in rems} | {k for k, _p, _s in open_rems}
    kps = await dashboard.kp_info(scope, kp_ids)

    per_kp: dict[uuid.UUID, Counter[str]] = defaultdict(Counter)
    for _s, _c, kp, is_failed, n in snap.tries:
        per_kp[kp]["ended"] += n
        per_kp[kp]["failed"] += n if is_failed else 0
    kp_fails = [
        tf.KpFailIn(
            concept_ref=ctx.ref(kps[k].concept_id),
            concept_title=ctx.title(kps[k].concept_id),
            kp_slug=kps[k].slug,
            kp_title=kps[k].title,
            failed=c["failed"],
            ended=c["ended"],
        )
        for k, c in per_kp.items()
        if k in kps
    ]

    picks: dict[uuid.UUID, Counter[uuid.UUID]] = defaultdict(Counter)
    for _s, iid, mid, _opt, _step in chosen:
        if iid in items and mid in miscs:
            picks[mid][items[iid].concept_id] += 1
    misconceptions = []
    for mid, by_concept in picks.items():
        cid = min(by_concept, key=lambda c: (-by_concept[c], ctx.order(c)))
        misconceptions.append(
            tf.StudentMisconceptionIn(
                id=mid,
                title=miscs[mid].title,
                concept_ref=ctx.ref(cid),
                concept_title=ctx.title(cid),
                count=sum(by_concept.values()),
            )
        )

    causes: dict[tuple[uuid.UUID, uuid.UUID], str] = {}
    for kp, prereq, state in open_rems:
        causes.setdefault((kp, prereq), state.value)
    for r in rems:
        causes.setdefault((r.kp_id, r.prereq_id), r.state.value)
    cause_rows = [
        tf.StudentCauseIn(
            kp_slug=kps[kp].slug,
            kp_title=kps[kp].title,
            concept_ref=ctx.ref(kps[kp].concept_id),
            concept_title=ctx.title(kps[kp].concept_id),
            prereq_ref=ctx.ref(prereq),
            prereq_title=ctx.title(prereq),
            state=state,  # type: ignore[arg-type]
        )
        for (kp, prereq), state in causes.items()
        if kp in kps and prereq in ctx.graph.nodes and kps[kp].concept_id in ctx.graph.nodes
    ]

    stuck.sort(key=lambda s: ctx.order(ctx.graph.by_ref[s.ref]))
    return tf.StudentInput(
        student_id=sid,
        learned=snap.learned,
        total=len(concepts),
        learn_seconds=snap.study.get(StudyActivity.learn, 0),
        practice_seconds=snap.study.get(StudyActivity.practice, 0),
        week_xp=snap.week_xp,
        streak_days=snap.streak_days,
        reviews_due=snap.reviews_due,
        last_quiz_pct=None if snap.last_quiz is None else snap.last_quiz.score_pct,
        stuck=stuck,
        in_progress=in_progress,
        kp_fails=kp_fails,
        misconceptions=misconceptions,
        causes=cause_rows,
        weak_memory=[(ref, t) for _r, ref, t in sorted(weak_mem)],
        fading_memory=[(ref, t) for _r, ref, t in sorted(fading_mem)],
        at_risk=[r.detail for r in snap.reasons],
        hints_per_10=dashboard.per_10(snap.hints, snap.answered),
        assignments=[
            tf.StudentAssignmentIn(a.id, a.title, a.due_date, a.status, a.learned, a.total)
            for a in snap.assignment_rows
        ],
    )


# --- rows -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    class_id: uuid.UUID
    kind: Kind
    window: Window
    student_id: uuid.UUID | None = None


def _for_target(scope: OrgScope, t: Target) -> Any:
    stmt = scope.select(TeacherSummary).where(
        TeacherSummary.class_id == t.class_id,
        TeacherSummary.kind == t.kind,
        TeacherSummary.window == t.window,
    )
    if t.student_id is None:
        return stmt.where(TeacherSummary.student_id.is_(None))
    return stmt.where(TeacherSummary.student_id == t.student_id)


async def _latest_usable(scope: OrgScope, t: Target) -> TeacherSummary | None:
    stmt = (
        _for_target(scope, t)
        .where(TeacherSummary.status.in_(USABLE))
        .order_by(TeacherSummary.created_at.desc())
        .limit(1)
    )
    return (await scope.session.scalars(stmt)).first()


def _live_pending(now: datetime) -> Any:
    return (TeacherSummary.status == Status.pending) & (
        TeacherSummary.created_at > now - lim.STALE_PENDING
    )


def _counted(now: datetime) -> Any:
    return TeacherSummary.status.in_(COUNTED[1:]) | _live_pending(now)


async def _busy(scope: OrgScope, t: Target, now: datetime) -> bool:
    stmt = _for_target(scope, t).where(_live_pending(now)).limit(1)
    return (await scope.session.scalars(stmt)).first() is not None


async def _used(scope: OrgScope, now: datetime) -> tuple[int, int]:
    """(this teacher's, this school's) generations today (IST)."""
    row = (
        await scope.session.execute(
            scope.select(TeacherSummary)
            .with_only_columns(
                func.count().filter(TeacherSummary.created_by == scope.user.id),
                func.count(),
            )
            .where(TeacherSummary.day == _ist_day(now), _counted(now))
        )
    ).one()
    return int(row[0]), int(row[1])


def _blocked(
    ctx: ClassCtx,
    enough: bool,
    latest: TeacherSummary | None,
    hash_: str,
    busy: bool,
    used: tuple[int, int],
    now: datetime,
) -> Blocked | None:
    if ctx.cls.archived_at is not None:
        return "archived"
    if not enough:
        return "not_enough_data"
    if used[0] >= lim.TEACHER_DAILY_CAP:
        return "teacher_cap"
    if used[1] >= lim.SCHOOL_DAILY_CAP:
        return "school_cap"
    if latest is not None and latest.facts_hash == hash_ and latest.created_at > now - lim.COOLDOWN:
        return "fresh"
    if busy:
        return "busy"
    return None


def _problem(blocked: Blocked, now: datetime) -> ApiProblem:
    resets = {"resets_at": kp_flow.next_midnight_ist(now).isoformat()}
    if blocked == "archived":
        return ApiProblem(409, "class_archived", "This class is archived.")
    if blocked == "not_enough_data":
        return ApiProblem(422, "not_enough_data", NOT_ENOUGH)
    if blocked == "teacher_cap":
        return ApiProblem(
            429,
            "teacher_ai_daily_cap",
            f"You've used today's {lim.TEACHER_DAILY_CAP} summaries. More after midnight.",
            extra=resets,
        )
    if blocked == "school_cap":
        return ApiProblem(
            429,
            "school_ai_daily_cap",
            "Your school has used today's summaries. More after midnight.",
            extra=resets,
        )
    if blocked == "fresh":
        return ApiProblem(409, "summary_fresh", "Nothing has changed since the last summary.")
    return ApiProblem(
        409, "summary_busy", "A summary is already being written. Try again in a couple of minutes."
    )


def _unavailable() -> ApiProblem:
    return ApiProblem(503, "teacher_ai_unavailable", "AI summaries aren't available right now.")


# --- rendering ------------------------------------------------------------------------------------


def _names(ctx: ClassCtx, kind: Kind) -> dict[uuid.UUID, str]:
    if kind == Kind.student:
        return {ctx.students[0].id: ctx.students[0].display_name}
    return {s.id: s.display_name for s in ctx.students}


def _fill(text_: str, fs: FactSet, names: dict[uuid.UUID, str]) -> str:
    def name(m: Any) -> str:
        sid = fs.pseudonyms.get(f"S{m.group(1)}")
        return names.get(sid, GONE) if sid is not None else GONE

    return TOKEN.sub(name, text_)


def _link(source: dict[str, Any], fs: FactSet, names: dict[uuid.UUID, str]) -> FactLink:
    kind = source.get("kind", "overview_card")
    if kind == "student":
        sid = fs.pseudonyms.get(source.get("student", ""))
        return FactLink(kind="student", student_id=sid if sid in names else None)
    if kind in ("misconception", "assignment"):
        return FactLink(kind=kind, id=uuid.UUID(source["id"]))
    if kind == "concept":
        return FactLink(kind="concept", concept=source.get("concept"))
    if kind == "student_section":
        return FactLink(kind="student_section", section=source.get("section"))
    return FactLink(kind="overview_card", card=source.get("card"))


async def _render(
    scope: OrgScope, ctx: ClassCtx, row: TeacherSummary, creator: str | None = None
) -> Summary:
    fs = FactSet.from_json(row.facts, row.pseudonyms)
    out = ModelOutput.model_validate(row.content or {"summary": []})
    names = _names(ctx, row.kind)
    if creator is None:
        creator = (
            await scope.session.scalars(
                scope.select(AppUser)
                .with_only_columns(AppUser.display_name)
                .where(AppUser.id == row.created_by)
            )
        ).first() or "A teacher"
    cited: list[str] = []

    def claim(c: Any) -> ClaimOut:
        cited.extend(f for f in c.facts if f not in cited)
        return ClaimOut(text=_fill(c.text, fs, names), citations=list(c.facts))

    claims = [claim(c) for c in out.summary]
    notes = []
    for n in out.notes:
        why = claim(n.why)
        revisit = []
        for rid in n.revisit:
            r = fs.resource(rid)
            if r is None:
                continue
            cid = ctx.graph.by_ref.get(r.concept)
            revisit.append(
                ResourceOut(
                    id=r.id,
                    kind=r.kind,
                    title=r.title,
                    concept=r.concept,
                    concept_title=r.concept_title,
                    kp=r.kp,
                    available=cid is not None,
                    in_course=cid is not None and cid in ctx.concept_set,
                )
            )
        group = [
            StudentRef(student_id=sid, display_name=names[sid])
            for p in n.group
            if (sid := fs.pseudonyms.get(p)) is not None and sid in names
        ]
        if row.kind == Kind.student:
            sid = ctx.students[0].id
            in_scope = ctx.students[0].status != UserStatus.deactivated
            students: list[uuid.UUID] | None = [sid] if in_scope else []
        else:
            students = [g.student_id for g in group] if n.group else None
        notes.append(
            NoteOut(
                focus=n.focus,
                why=why,
                revisit=revisit,
                group=group,
                assign=AssignPrefill(
                    concepts=list(dict.fromkeys(r.concept for r in revisit if r.in_course)),
                    student_ids=students,
                ),
            )
        )
    facts = [
        FactOut(id=f.id, text=_fill(f.text, fs, names), link=_link(f.source, fs, names))
        for fid in cited
        if (f := fs.fact(fid)) is not None
    ]
    assert row.status in USABLE
    return Summary(
        id=row.id,
        kind=row.kind.value,
        window=row.window,
        status=row.status.value,
        created_at=row.created_at,
        created_by_name=creator,
        claims=claims,
        notes=notes,
        facts=facts,
    )


# --- endpoints ------------------------------------------------------------------------------------


async def _facts(scope: OrgScope, ctx: ClassCtx, t: Target) -> FactSet:
    if t.kind == Kind.student:
        return tf.student_facts(await student_input(scope, ctx))
    return tf.class_facts(await class_input(scope, ctx, t.window))


async def _load(scope: OrgScope, t: Target) -> ClassCtx:
    return await class_view.load(scope, t.class_id, student_id=t.student_id)


async def _state(scope: OrgScope, t: Target, client: TeacherClient | None) -> SummaryState:
    ctx = await _load(scope, t)
    now = datetime.now(UTC)
    resets = kp_flow.next_midnight_ist(now)
    if client is None:
        return SummaryState(
            enabled=False,
            enough_data=False,
            summary=None,
            stale=False,
            can_regenerate=False,
            blocked=None,
            daily_left=0,
            resets_at=resets,
        )
    fs = await _facts(scope, ctx, t)
    enough = tf.enough_data(fs)
    hash_ = tf.facts_hash(fs)
    latest = await _latest_usable(scope, t)
    used = await _used(scope, now)
    busy = await _busy(scope, t, now)
    blocked = _blocked(ctx, enough, latest, hash_, busy, used, now)
    return SummaryState(
        enabled=True,
        enough_data=enough,
        summary=None if latest is None else await _render(scope, ctx, latest),
        stale=latest is not None and latest.facts_hash != hash_,
        can_regenerate=blocked is None,
        blocked=blocked,
        daily_left=max(0, min(lim.TEACHER_DAILY_CAP - used[0], lim.SCHOOL_DAILY_CAP - used[1])),
        resets_at=resets,
    )


async def _reserve(scope: OrgScope, ctx: ClassCtx, t: Target, fs: FactSet) -> uuid.UUID:
    """Tx 1: lock the school, retire stale pending rows, check, insert the pending row."""
    now = datetime.now(UTC)
    await scope.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"teacher_ai:{scope.org_id}"},
    )
    await scope.session.execute(
        update(TeacherSummary)
        .where(
            TeacherSummary.org_id == scope.org_id,
            TeacherSummary.status == Status.pending,
            TeacherSummary.created_at <= now - lim.STALE_PENDING,
        )
        .values(status=Status.error, updated_at=now)
    )
    hash_ = tf.facts_hash(fs)
    blocked = _blocked(
        ctx,
        tf.enough_data(fs),
        await _latest_usable(scope, t),
        hash_,
        await _busy(scope, t, now),
        await _used(scope, now),
        now,
    )
    if blocked is not None:
        await scope.session.rollback()
        raise _problem(blocked, now)
    row = TeacherSummary(
        org_id=scope.org_id,
        class_id=t.class_id,
        student_id=t.student_id,
        kind=t.kind,
        window=t.window,
        status=Status.pending,
        facts=fs.to_json(),
        pseudonyms={p: str(sid) for p, sid in fs.pseudonyms.items()},
        facts_hash=hash_,
        created_by=scope.user.id,
        day=_ist_day(now),
    )
    scope.session.add(row)
    await scope.session.flush()
    row_id = row.id
    await scope.session.commit()
    return row_id


async def _close(scope: OrgScope, row_id: uuid.UUID) -> None:
    """Mark a reserved row `error` (not counted), best effort."""
    try:
        await scope.session.rollback()
        await scope.session.execute(
            update(TeacherSummary)
            .where(
                TeacherSummary.org_id == scope.org_id,
                TeacherSummary.id == row_id,
                TeacherSummary.status == Status.pending,
            )
            .values(status=Status.error, updated_at=func.now())
        )
        await scope.session.commit()
    except Exception:
        log.warning("teacher summary %s: couldn't close the pending row", row_id)


async def _store(scope: OrgScope, row_id: uuid.UUID, result: SummaryResult) -> TeacherSummary:
    """Tx 2."""
    row = await scope.get(TeacherSummary, row_id, for_update=True)
    row.status = Status(result.status)
    row.content = None if result.output is None else result.output.model_dump()
    row.dropped = [list(d) for d in result.dropped]
    row.model = result.model
    row.input_tokens = result.input_tokens
    row.output_tokens = result.output_tokens
    row.cache_read_tokens = result.cache_read_tokens
    row.cache_write_tokens = result.cache_write_tokens
    row.latency_ms = result.latency_ms
    row.calls = result.calls
    row.updated_at = datetime.now(UTC)
    await scope.session.commit()
    log.info(
        "teacher summary %s: %s, calls=%s, tokens in=%s cached=%s out=%s",
        row.id,
        row.status.value,
        row.calls,
        row.input_tokens,
        row.cache_read_tokens,
        row.output_tokens,
    )
    return row


async def _create(scope: OrgScope, t: Target, client: TeacherClient | None) -> Summary:
    ctx = await _load(scope, t)
    if client is None:
        raise _unavailable()
    fs = await _facts(scope, ctx, t)
    row_id = await _reserve(scope, ctx, t, fs)
    try:
        result = await run_summary(fs, client, get_settings().teacher_ai_model)
    except TeacherAIUnavailable as exc:
        log.warning("teacher summary %s: provider unavailable (%s)", row_id, exc)
        await _close(scope, row_id)
        raise _unavailable() from None
    except BaseException:
        await _close(scope, row_id)
        raise
    row = await _store(scope, row_id, result)
    if row.status == Status.failed:
        raise ApiProblem(
            502,
            "summary_failed",
            "Couldn't write a summary this time. The dashboard numbers are unaffected.",
        )
    creator = (
        await scope.session.scalars(
            scope.select(AppUser)
            .with_only_columns(AppUser.display_name)
            .where(AppUser.id == scope.user.id)
        )
    ).first()
    return await _render(scope, ctx, row, creator)


def _class_target(class_id: uuid.UUID, window: Window) -> Target:
    return Target(class_id=class_id, kind=Kind.class_, window=window)


def _student_target(class_id: uuid.UUID, student_id: uuid.UUID) -> Target:
    return Target(class_id=class_id, kind=Kind.student, window="7d", student_id=student_id)


async def get_class_summary(
    scope: OrgScope, class_id: uuid.UUID, window: Window, client: TeacherClient | None
) -> SummaryState:
    return await _state(scope, _class_target(class_id, window), client)


async def create_class_summary(
    scope: OrgScope, class_id: uuid.UUID, window: Window, client: TeacherClient | None
) -> Summary:
    return await _create(scope, _class_target(class_id, window), client)


async def get_student_summary(
    scope: OrgScope, class_id: uuid.UUID, student_id: uuid.UUID, client: TeacherClient | None
) -> SummaryState:
    return await _state(scope, _student_target(class_id, student_id), client)


async def create_student_summary(
    scope: OrgScope, class_id: uuid.UUID, student_id: uuid.UUID, client: TeacherClient | None
) -> Summary:
    return await _create(scope, _student_target(class_id, student_id), client)
