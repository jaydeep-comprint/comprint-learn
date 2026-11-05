"""Facts for teacher summaries (spec 011): the model's only input about a class or student.

Pure: the service turns 010's dashboard snapshot into a `ClassInput` / `StudentInput` and the
builders here turn that into numbered facts (`F1`…) and resources (`R1`…). Students appear only as
`{Sn}` pseudonym tokens, numbered by first appearance; the map to ids stays server side. Only
fact ids and text (and resource ids, kinds and titles) are rendered for the model.
"""

import hashlib
import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from app.ai import teacher_limits as lim

Kind = Literal["class", "student"]
WindowName = Literal["7d", "30d", "all"]
PERIOD = {"7d": "(last 7 days)", "30d": "(last 30 days)", "all": "(all time)"}
AT_RISK_PERIOD = "(last 7 days)"
REPLY_NOW = "Reply with the JSON object now."
TOKEN = re.compile(r"\{S(\d+)\}")  # a pseudonym token; "{S10}" never reads as "{S1}" + "0"


# --- output ---------------------------------------------------------------------------------------


@dataclass
class Fact:
    id: str
    kind: str
    text: str  # with {Sn} tokens
    students: list[str]  # pseudonyms ("S1"), server side only
    source: dict[str, Any]  # where its chip links, server side only

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "students": self.students,
            "source": self.source,
        }


@dataclass
class Resource:
    id: str
    kind: Literal["lesson", "worked_example"]
    title: str  # concept title (lesson) or KP title (worked example)
    concept: str  # "<course>/<slug>" of the concept the lesson belongs to
    concept_title: str
    kp: str | None = None  # KP slug for a worked example

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "concept": self.concept,
            "concept_title": self.concept_title,
            "kp": self.kp,
        }

    @property
    def label(self) -> str:
        if self.kind == "lesson":
            return f"Lesson: '{self.title}'"
        return f"Worked example: KP '{self.title}' ('{self.concept_title}')"


@dataclass
class FactSet:
    kind: Kind
    window: WindowName
    facts: list[Fact] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)
    pseudonyms: dict[str, uuid.UUID] = field(default_factory=dict)  # "S1" -> student id

    def fact(self, fid: str) -> Fact | None:
        return next((f for f in self.facts if f.id == fid), None)

    def resource(self, rid: str) -> Resource | None:
        return next((r for r in self.resources if r.id == rid), None)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "window": self.window,
            "facts": [f.as_json() for f in self.facts],
            "resources": [r.as_json() for r in self.resources],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any], pseudonyms: dict[str, Any]) -> "FactSet":
        return cls(
            kind=data["kind"],
            window=data["window"],
            facts=[Fact(**f) for f in data["facts"]],
            resources=[Resource(**r) for r in data["resources"]],
            pseudonyms={k: uuid.UUID(str(v)) for k, v in pseudonyms.items()},
        )


# --- input (built by services/teacher_ai.py from 010's snapshot) --------------------------------


@dataclass(frozen=True)
class KpTries:
    slug: str
    title: str
    failed: int
    ended: int


@dataclass(frozen=True)
class WeakConcept:
    ref: str
    title: str
    chapter: str
    tries: int
    failed: int
    students_tried: int
    stuck_now: int
    learned_pct: int
    kps: tuple[KpTries, ...] = ()


@dataclass(frozen=True)
class MisconceptionIn:
    id: uuid.UUID
    title: str
    concept_ref: str | None
    concept_title: str | None
    chosen: int
    offered: int
    students: tuple[uuid.UUID, ...]  # who chose it, in a stable order


@dataclass(frozen=True)
class CauseNow:
    prereq_ref: str
    prereq_title: str
    concept_ref: str
    concept_title: str
    review_due: tuple[uuid.UUID, ...]
    relearn: tuple[uuid.UUID, ...]

    @property
    def students(self) -> tuple[uuid.UUID, ...]:
        return self.review_due + self.relearn


@dataclass(frozen=True)
class CauseWindow:
    kp_slug: str
    kp_title: str
    concept_ref: str
    concept_title: str
    prereq_ref: str
    prereq_title: str
    students: tuple[uuid.UUID, ...]
    resolved: int


@dataclass(frozen=True)
class AssignmentIn:
    id: uuid.UUID
    title: str
    due: date
    done: int
    total: int
    overdue: int
    not_started: int


@dataclass(frozen=True)
class ClassInput:
    window: WindowName
    students_in_scope: int
    learn_seconds: int
    practice_seconds: int
    weak_concepts: Sequence[WeakConcept] = ()
    misconceptions: Sequence[MisconceptionIn] = ()
    causes_now: Sequence[CauseNow] = ()
    causes_window: Sequence[CauseWindow] = ()
    at_risk: Sequence[tuple[uuid.UUID, Sequence[str]]] = ()  # 010 order
    hints_per_10: float | None = None
    hint_top: Sequence[tuple[uuid.UUID, float]] = ()
    assignments: Sequence[AssignmentIn] = ()


@dataclass(frozen=True)
class StuckIn:
    ref: str
    title: str
    label: str  # "brushing up 'Integers'" | "relearning 'Integers'" | "waiting to retry"


@dataclass(frozen=True)
class KpFailIn:
    concept_ref: str
    concept_title: str
    kp_slug: str
    kp_title: str
    failed: int
    ended: int


@dataclass(frozen=True)
class StudentMisconceptionIn:
    id: uuid.UUID
    title: str
    concept_ref: str | None
    concept_title: str | None
    count: int


@dataclass(frozen=True)
class StudentCauseIn:
    kp_slug: str
    kp_title: str
    concept_ref: str
    concept_title: str
    prereq_ref: str
    prereq_title: str
    state: Literal["review_due", "relearn", "resolved"]


@dataclass(frozen=True)
class StudentAssignmentIn:
    id: uuid.UUID
    title: str
    due: date
    status: str  # 010's StudentStatus, e.g. "overdue"
    learned: int
    total: int


@dataclass(frozen=True)
class StudentInput:
    student_id: uuid.UUID
    learned: int
    total: int
    learn_seconds: int
    practice_seconds: int
    week_xp: int
    streak_days: int
    reviews_due: int
    last_quiz_pct: int | None = None
    stuck: Sequence[StuckIn] = ()
    in_progress: Sequence[tuple[str, str]] = ()  # (ref, title)
    kp_fails: Sequence[KpFailIn] = ()
    misconceptions: Sequence[StudentMisconceptionIn] = ()
    causes: Sequence[StudentCauseIn] = ()
    weak_memory: Sequence[tuple[str, str]] = ()  # (ref, title), weakest first
    fading_memory: Sequence[tuple[str, str]] = ()
    at_risk: Sequence[str] = ()  # AtRiskReason.detail
    hints_per_10: float | None = None
    assignments: Sequence[StudentAssignmentIn] = ()


# --- builder --------------------------------------------------------------------------------------


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def _day(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def _num(x: float) -> str:
    return f"{x:.1f}"


def _quote(title: str) -> str:
    return f"'{title}'"


def _list(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


STATE_WORDS = {"review_due": "brushing up", "relearn": "relearning", "resolved": "resolved"}


class _Builder:
    def __init__(self, kind: Kind, window: WindowName) -> None:
        self.out = FactSet(kind=kind, window=window)
        self._ids: dict[uuid.UUID, str] = {}
        self._res: dict[tuple[str, str, str | None], str] = {}

    def token(self, sid: uuid.UUID) -> str:
        p = self._ids.get(sid)
        if p is None:
            p = f"S{len(self._ids) + 1}"
            self._ids[sid] = p
            self.out.pseudonyms[p] = sid
        return p

    def names(self, sids: Sequence[uuid.UUID]) -> tuple[str, list[str]]:
        """'{S1}, {S2} and 3 more' plus the pseudonyms named."""
        shown = [self.token(s) for s in sids[: lim.FACT_STUDENTS]]
        text = [f"{{{p}}}" for p in shown]
        rest = len(sids) - len(shown)
        if rest > 0:
            text.append(f"{rest} more")
        return _list(text), shown

    def add(self, kind: str, text: str, students: Sequence[str], source: dict[str, Any]) -> None:
        fid = f"F{len(self.out.facts) + 1}"
        self.out.facts.append(Fact(fid, kind, text, list(students), source))

    def lesson(self, ref: str, title: str) -> None:
        self._resource("lesson", ref, title, title, None)

    def worked_example(self, ref: str, concept_title: str, kp_slug: str, kp_title: str) -> None:
        self._resource("worked_example", ref, kp_title, concept_title, kp_slug)

    def _resource(
        self,
        kind: Literal["lesson", "worked_example"],
        ref: str,
        title: str,
        concept_title: str,
        kp: str | None,
    ) -> None:
        key = (kind, ref, kp)
        if key in self._res or len(self.out.resources) >= lim.MAX_RESOURCES:
            return
        rid = f"R{len(self.out.resources) + 1}"
        self._res[key] = rid
        self.out.resources.append(Resource(rid, kind, title, ref, concept_title, kp))


def class_facts(inp: ClassInput) -> FactSet:
    b = _Builder("class", inp.window)
    period = PERIOD[inp.window]
    active = inp.learn_seconds + inp.practice_seconds
    if active:
        time_text = (
            f"Active time: practice {_pct(inp.practice_seconds, active)}%, "
            f"learn {_pct(inp.learn_seconds, active)}% {period}."
        )
    else:
        time_text = f"No active time recorded {period}."
    b.add(
        "class",
        f"{inp.students_in_scope} students in scope. {time_text}",
        [],
        {"kind": "overview_card", "card": "time"},
    )

    for c in inp.weak_concepts[: lim.TOP_CONCEPTS]:
        b.add(
            "weak_concept",
            f"Concept {_quote(c.title)} (chapter {_quote(c.chapter)}): {c.failed} of {c.tries} "
            f"KP tries failed ({_pct(c.failed, c.tries)}%) by {c.students_tried} students; "
            f"{c.stuck_now} stuck now; {c.learned_pct}% learned {period}.",
            [],
            {"kind": "concept", "concept": c.ref},
        )
        b.lesson(c.ref, c.title)
        kps = sorted(
            (k for k in c.kps if k.ended >= lim.MIN_KP_TRIES and k.failed > 0),
            key=lambda k: (-k.failed / k.ended, -k.ended),
        )[: lim.KPS_PER_CONCEPT]
        for k in kps:
            b.add(
                "weak_kp",
                f"KP {_quote(k.title)} ({_quote(c.title)}): {k.failed} of {k.ended} tries "
                f"failed {period}.",
                [],
                {"kind": "concept", "concept": c.ref},
            )
            b.worked_example(c.ref, c.title, k.slug, k.title)

    for m in inp.misconceptions[: lim.TOP_MISCONCEPTIONS]:
        where = f" ({_quote(m.concept_title)})" if m.concept_title else ""
        rate = f" ({_pct(m.chosen, m.offered)}%)" if m.offered else ""
        named, shown = b.names(m.students)
        by = f" by {named}" if named else ""
        b.add(
            "misconception",
            f"Misconception {_quote(m.title)}{where}: chosen in {m.chosen} of {m.offered} "
            f"answers{rate}{by} {period}.",
            shown,
            {"kind": "misconception", "id": str(m.id)},
        )
        if m.concept_ref and m.concept_title:
            b.lesson(m.concept_ref, m.concept_title)

    causes_now = sorted(inp.causes_now, key=lambda c: -len(c.students))[: lim.TOP_CAUSES]
    for cn in causes_now:
        named, shown = b.names(cn.students)
        parts = []
        if cn.review_due:
            parts.append(f"{len(cn.review_due)} brushing up")
        if cn.relearn:
            parts.append(f"{len(cn.relearn)} relearning")
        b.add(
            "cause_now",
            f"Prerequisite {_quote(cn.prereq_title)} is the open cause for "
            f"{len(cn.students)} students stuck in {_quote(cn.concept_title)} ({named}): "
            f"{', '.join(parts)}.",
            shown,
            {"kind": "concept", "concept": cn.concept_ref},
        )
        b.lesson(cn.concept_ref, cn.concept_title)
        b.lesson(cn.prereq_ref, cn.prereq_title)

    causes_window = sorted(inp.causes_window, key=lambda c: -len(c.students))[: lim.TOP_CAUSES]
    for cw in causes_window:
        named, shown = b.names(cw.students)
        b.add(
            "cause_window",
            f"Repeated fails on KP {_quote(cw.kp_title)} ({_quote(cw.concept_title)}) sent "
            f"{len(cw.students)} students to prerequisite {_quote(cw.prereq_title)} ({named}); "
            f"{cw.resolved} have resolved it {period}.",
            shown,
            {"kind": "concept", "concept": cw.concept_ref},
        )
        b.worked_example(cw.concept_ref, cw.concept_title, cw.kp_slug, cw.kp_title)
        b.lesson(cw.prereq_ref, cw.prereq_title)

    for sid, details in inp.at_risk[: lim.MAX_AT_RISK]:
        p = b.token(sid)
        b.add(
            "at_risk",
            f"{{{p}}} is at risk: {'; '.join(details)} {AT_RISK_PERIOD}.",
            [p],
            {"kind": "student", "student": p},
        )

    if inp.hints_per_10 is not None:
        text = f"Class: {_num(inp.hints_per_10)} hints per 10 questions"
        hinted: list[str] = []
        if inp.hint_top:
            tops = []
            for sid, per in inp.hint_top:
                p = b.token(sid)
                hinted.append(p)
                tops.append(f"{{{p}}} {_num(per)}")
            text += ". Highest: " + ", ".join(tops)
        b.add("hints", f"{text} {period}.", hinted, {"kind": "overview_card", "card": "hints"})

    for a in inp.assignments[: lim.MAX_ASSIGNMENTS]:
        b.add(
            "assignment",
            f"Assignment {_quote(a.title)} due {_day(a.due)}: {a.done} of {a.total} done, "
            f"{a.overdue} overdue, {a.not_started} not started.",
            [],
            {"kind": "assignment", "id": str(a.id)},
        )
    return b.out


def student_facts(inp: StudentInput) -> FactSet:
    b = _Builder("student", "7d")
    me = b.token(inp.student_id)  # always S1
    tok = f"{{{me}}}"
    s = [me]

    active = inp.learn_seconds + inp.practice_seconds
    parts = [f"{tok}: {inp.learned} of {inp.total} concepts learned"]
    if active:
        parts.append(
            f"{round(active / 60)} active minutes (practice {_pct(inp.practice_seconds, active)}%)"
        )
    else:
        parts.append("no active time recorded")
    parts.append(f"{inp.week_xp} XP this week")
    parts.append(f"streak {inp.streak_days} days")
    parts.append(f"{inp.reviews_due} reviews due")
    if inp.last_quiz_pct is not None:
        parts.append(f"last quiz {inp.last_quiz_pct}%")
    b.add("student", "; ".join(parts) + " (last 7 days).", s, _section("stats"))

    if inp.stuck or inp.in_progress:
        chunks = []
        if inp.stuck:
            items = [f"{_quote(x.title)} ({x.label})" for x in inp.stuck[: lim.STUDENT_STATES]]
            chunks.append("Stuck: " + ", ".join(items) + ".")
        if inp.in_progress:
            titles = [_quote(t) for _r, t in inp.in_progress[: lim.STUDENT_STATES]]
            chunks.append("In progress: " + ", ".join(titles) + ".")
        b.add("states", " ".join(chunks), s, _section("graph"))
        for x in inp.stuck[: lim.STUDENT_STATES]:
            b.lesson(x.ref, x.title)

    fails = sorted((k for k in inp.kp_fails if k.failed > 0), key=lambda k: (-k.failed, -k.ended))[
        : lim.STUDENT_KP_FAILS
    ]
    for k in fails:
        b.add(
            "kp_fails",
            f"KP {_quote(k.kp_title)} ({_quote(k.concept_title)}): failed {k.failed} of "
            f"{k.ended} tries (last 7 days).",
            s,
            {"kind": "concept", "concept": k.concept_ref},
        )
        b.worked_example(k.concept_ref, k.concept_title, k.kp_slug, k.kp_title)

    for m in sorted(inp.misconceptions, key=lambda m: -m.count)[: lim.STUDENT_MISCONCEPTIONS]:
        where = f" ({_quote(m.concept_title)})" if m.concept_title else ""
        times = "once" if m.count == 1 else f"{m.count} times"
        b.add(
            "misconception",
            f"Chose misconception {_quote(m.title)} {times}{where} (last 7 days).",
            s,
            _section("activity"),
        )
        if m.concept_ref and m.concept_title:
            b.lesson(m.concept_ref, m.concept_title)

    for c in inp.causes:
        state = "open, " + STATE_WORDS[c.state] if c.state != "resolved" else "resolved"
        b.add(
            "cause",
            f"Repeated fails on KP {_quote(c.kp_title)} ({_quote(c.concept_title)}) sent {tok} "
            f"to prerequisite {_quote(c.prereq_title)} ({state}).",
            s,
            _section("graph"),
        )
        b.worked_example(c.concept_ref, c.concept_title, c.kp_slug, c.kp_title)
        b.lesson(c.prereq_ref, c.prereq_title)

    if inp.weak_memory or inp.fading_memory:
        chunks = []
        if inp.weak_memory:
            weak = [_quote(t) for _r, t in inp.weak_memory[: lim.STUDENT_MEMORY]]
            chunks.append("Weak memory: " + ", ".join(weak) + ".")
        if inp.fading_memory:
            fading = [_quote(t) for _r, t in inp.fading_memory[: lim.STUDENT_MEMORY]]
            chunks.append("Fading: " + ", ".join(fading) + ".")
        b.add("memory", " ".join(chunks), s, _section("graph"))
        for ref, title in inp.weak_memory[: lim.STUDENT_MEMORY]:
            b.lesson(ref, title)

    if inp.at_risk:
        b.add(
            "at_risk",
            "At risk: " + "; ".join(inp.at_risk) + f" {AT_RISK_PERIOD}.",
            s,
            _section("stats"),
        )

    if inp.hints_per_10 is not None:
        b.add(
            "hints",
            f"{_num(inp.hints_per_10)} hints per 10 questions (last 7 days).",
            s,
            _section("stats"),
        )

    for a in inp.assignments[: lim.MAX_ASSIGNMENTS]:
        b.add(
            "assignment",
            f"Assignment {_quote(a.title)} due {_day(a.due)}: {a.status.replace('_', ' ')}, "
            f"{a.learned} of {a.total} concepts learned.",
            s,
            _section("assignments"),
        )
    return b.out


def _section(name: str) -> dict[str, Any]:
    return {"kind": "student_section", "section": name}


CLASS_SIGNAL = {"weak_concept", "misconception", "cause_now", "cause_window", "at_risk"}
STUDENT_SIGNAL = {"kp_fails", "misconception", "cause", "memory", "at_risk"}


def enough_data(fs: FactSet) -> bool:
    kinds = {f.kind for f in fs.facts}
    if fs.kind == "class":
        return bool(kinds & CLASS_SIGNAL)
    if kinds & STUDENT_SIGNAL:
        return True
    return any(f.kind == "states" and f.text.startswith("Stuck:") for f in fs.facts)


def render(fs: FactSet) -> str:
    """The user turn: facts and resources as data, then the closing line JSON mode needs."""
    if fs.kind == "class":
        head = f"CLASS SUMMARY. Period: {PERIOD[fs.window].strip('()')}."
    else:
        head = "STUDENT SUMMARY for {S1}. Period: last 7 days, plus current states."
    facts = "\n".join(f"{f.id}: {_esc(f.text)}" for f in fs.facts)
    resources = "\n".join(f"{r.id}: {_esc(r.label)}" for r in fs.resources) or "(none)"
    return (
        f"{head}\n\n<facts>\n{facts}\n</facts>\n\n<resources>\n{resources}\n</resources>"
        f"\n\n{REPLY_NOW}"
    )


def _esc(text: str) -> str:
    return text.replace("<", "&lt;")


def facts_hash(fs: FactSet) -> str:
    """SHA-256 of the canonical facts (students as ids) and resources: staleness + cooldown."""
    payload = {
        "kind": fs.kind,
        "window": fs.window,
        "facts": [
            {
                "id": f.id,
                "kind": f.kind,
                "text": _with_ids(f.text, fs),
                "students": sorted(str(fs.pseudonyms[p]) for p in f.students),
            }
            for f in fs.facts
        ],
        "resources": [r.as_json() for r in fs.resources],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _with_ids(text: str, fs: FactSet) -> str:
    # Pseudonym numbers depend on order, so hash the ids they stand for.
    return TOKEN.sub(lambda m: str(fs.pseudonyms.get(f"S{m.group(1)}", m.group(0))), text)
