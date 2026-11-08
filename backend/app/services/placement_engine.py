"""The placement diagnostic's engine (spec 012). Pure: no DB, no clock; randomness is injected.

Evidence `e[c]` per range concept: a correct answer on c adds 1 to c and `w(a)` to each in-range
ancestor (the largest product of `encompassing_weight` along any path); a wrong answer (or "I
don't know") subtracts 1 from c and from each in-range descendant. A concept is decided at
`e >= 2`, `e <= -1` or after 2 direct questions.

Next question (decided with the user while building, replacing the spec's average): each askable,
undecided concept is scored by the *worse* of its two outcomes, counting progress toward a
decision over the whole range (1 for a concept the outcome decides, else the fraction of the way
to the threshold it moves toward). That is a binary search along the graph: on a chain the first
pick is around the upper middle. Ties go to the concept nearest the middle of the outline, then
the lowest id.
"""

import random
import uuid
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

MAX_QUESTIONS = 25
MAX_PER_CONCEPT = 2
LEARNED_E = 2.0
CONDITIONAL_E = 1.0
FAIL_E = -1.0
LEARNED_PRIOR = 1.0


@dataclass(frozen=True)
class Ev:
    e: float
    asked: int
    wrong: int


Evidence = dict[uuid.UUID, Ev]


@dataclass
class RangeGraph:
    """The frozen range: concepts in outline order and the in-range prerequisite edges."""

    concepts: list[uuid.UUID]
    parents: dict[uuid.UUID, list[uuid.UUID]] = field(default_factory=dict)
    children: dict[uuid.UUID, list[uuid.UUID]] = field(default_factory=dict)
    weight: dict[tuple[uuid.UUID, uuid.UUID], float] = field(default_factory=dict)
    order: dict[uuid.UUID, int] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        concepts: Sequence[uuid.UUID],
        edges: Iterable[tuple[uuid.UUID, uuid.UUID, float]],
    ) -> "RangeGraph":
        """`concepts` in outline order; `edges` are `(concept, prereq, weight)`, kept when both
        ends are in range."""
        g = cls(list(concepts))
        inside = set(g.concepts)
        g.order = {c: i for i, c in enumerate(g.concepts)}
        for c in g.concepts:
            g.parents[c] = []
            g.children[c] = []
        for c, p, w in edges:
            if c in inside and p in inside and c != p and (c, p) not in g.weight:
                g.parents[c].append(p)
                g.children[p].append(c)
                g.weight[(c, p)] = float(w)
        return g


def initial(g: RangeGraph, learned: set[uuid.UUID]) -> Evidence:
    return {c: Ev(LEARNED_PRIOR if c in learned else 0.0, 0, 0) for c in g.concepts}


def ancestor_weights(g: RangeGraph, c: uuid.UUID) -> dict[uuid.UUID, float]:
    """Every in-range ancestor of c with the largest path product of weights (all in (0, 1],
    so relaxing until nothing improves terminates)."""
    best: dict[uuid.UUID, float] = {c: 1.0}
    queue = deque([c])
    while queue:
        x = queue.popleft()
        for p in g.parents.get(x, []):
            w = best[x] * g.weight[(x, p)]
            if w > best.get(p, 0.0):
                best[p] = w
                queue.append(p)
    del best[c]
    return best


def descendants(g: RangeGraph, c: uuid.UUID) -> set[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    queue = deque(g.children.get(c, []))
    while queue:
        x = queue.popleft()
        if x not in seen:
            seen.add(x)
            queue.extend(g.children.get(x, []))
    return seen


def apply_answer(
    g: RangeGraph, ev: Mapping[uuid.UUID, Ev], c: uuid.UUID, correct: bool
) -> Evidence:
    out = dict(ev)
    cur = out[c]
    if correct:
        out[c] = Ev(cur.e + 1, cur.asked + 1, cur.wrong)
        for a, w in ancestor_weights(g, c).items():
            out[a] = replace(out[a], e=out[a].e + w)
    else:
        out[c] = Ev(cur.e - 1, cur.asked + 1, cur.wrong + 1)
        for d in descendants(g, c):
            out[d] = replace(out[d], e=out[d].e - 1)
    return out


def decided(ev: Ev) -> bool:
    return ev.e >= LEARNED_E or ev.e <= FAIL_E or ev.asked >= MAX_PER_CONCEPT


def _progress(before: Ev, after: Ev) -> float:
    """How far one undecided concept moved toward a decision (1 = decided)."""
    if decided(after):
        return 1.0
    delta = after.e - before.e
    if delta > 0:
        return min(1.0, delta / (LEARNED_E - before.e))
    if delta < 0:
        return min(1.0, -delta / (before.e - FAIL_E))
    return 0.0


def _gain(g: RangeGraph, ev: Evidence, c: uuid.UUID, correct: bool) -> float:
    after = apply_answer(g, ev, c, correct)
    return sum(_progress(ev[x], after[x]) for x in g.concepts if not decided(ev[x]))


def next_concept(g: RangeGraph, ev: Evidence, askable: set[uuid.UUID]) -> uuid.UUID | None:
    candidates = [c for c in g.concepts if c in askable and not decided(ev[c])]
    if not candidates:
        return None
    mid = (len(g.concepts) - 1) / 2

    def key(c: uuid.UUID) -> tuple[float, float, str]:
        score = min(_gain(g, ev, c, True), _gain(g, ev, c, False))
        return (-round(score, 9), abs(g.order[c] - mid), str(c))

    return min(candidates, key=key)


def finished(answered: int, ev: Evidence, askable: set[uuid.UUID]) -> bool:
    if answered >= MAX_QUESTIONS:
        return True
    return not any(c in ev and not decided(ev[c]) for c in askable)


def pick_item(
    kps: Sequence[Sequence[uuid.UUID]], served: set[uuid.UUID], rng: random.Random
) -> uuid.UUID | None:
    """`kps`: the concept's active quick `kp_question` item ids per KP, in KP order. The first
    question comes from the last KP, a second from a KP not used yet; else any unserved item."""
    free = [[i for i in items if i not in served] for items in kps]
    used = {k for k, items in enumerate(kps) if any(i in served for i in items)}
    if not used:
        preferred = [k for k in range(len(kps) - 1, -1, -1) if free[k]][:1]
    else:
        preferred = [k for k in range(len(kps)) if k not in used and free[k]]
    pool = [i for k in preferred for i in free[k]] or [i for items in free for i in items]
    if not pool:
        return None
    return rng.choice(sorted(pool, key=str))


def topo(g: RangeGraph, ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    """`ids` with prerequisites first (outline order breaks ties)."""
    wanted = set(ids)
    out: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()

    def visit(c: uuid.UUID) -> None:
        if c in seen:
            return
        seen.add(c)
        for p in sorted(g.parents.get(c, []), key=lambda x: g.order.get(x, 0)):
            visit(p)
        if c in wanted:
            out.append(c)

    for c in sorted(wanted, key=lambda x: g.order.get(x, len(g.order))):
        visit(c)
    return out


@dataclass
class Results:
    learned: list[uuid.UUID] = field(default_factory=list)
    conditional: list[uuid.UUID] = field(default_factory=list)
    demoted: list[uuid.UUID] = field(default_factory=list)
    confirmed: list[uuid.UUID] = field(default_factory=list)  # conditional -> plain learned


def classify(
    g: RangeGraph, ev: Evidence, *, learned: set[uuid.UUID], conditional: set[uuid.UUID]
) -> Results:
    """The final table, against the student's current `learned` set (and which of those are
    `conditional`). Placed concepts imply their unlearned in-range ancestors as conditional."""
    res = Results()
    placed: dict[uuid.UUID, bool] = {}  # concept -> conditional
    for c in g.concepts:
        x = ev.get(c)
        if x is None:
            continue
        if c in learned:
            if x.e >= LEARNED_E and c in conditional:
                res.confirmed.append(c)
            elif x.e <= FAIL_E and x.wrong >= 1:
                res.demoted.append(c)
        elif x.e >= LEARNED_E:
            placed[c] = False
        elif x.e >= CONDITIONAL_E:
            placed[c] = True
    implied: set[uuid.UUID] = set()
    for c in list(placed):
        for a in ancestor_weights(g, c):
            if a not in learned and a not in placed:
                implied.add(a)
    for a in implied:
        placed[a] = True
    for c in topo(g, placed):
        (res.conditional if placed[c] else res.learned).append(c)
    res.demoted = topo(g, res.demoted)
    res.confirmed = topo(g, res.confirmed)
    return res


def dump_evidence(ev: Evidence) -> dict[str, Any]:
    return {str(c): {"e": x.e, "asked": x.asked, "wrong": x.wrong} for c, x in ev.items()}


def load_evidence(doc: Mapping[str, Any] | None) -> Evidence:
    return {
        uuid.UUID(k): Ev(float(v["e"]), int(v["asked"]), int(v["wrong"]))
        for k, v in (doc or {}).items()
    }
