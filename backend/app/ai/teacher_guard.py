"""The citation guard for teacher summaries (spec 011). Pure; runs on every reply.

Per claim (summary claim or note `why`): cited fact ids must exist (unknown ones are stripped; no
valid one drops the claim); every number must appear in a cited fact (`43%` = `0.43`); every
`{Sn}` must be a student of a cited fact; no bare `S3`, email, uuid or 10-digit number; at most
1.5x the word limit. Notes also need a valid resource and keep only group members backed by
`group_facts`.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from app.ai import teacher_limits as lim
from app.ai.teacher_facts import TOKEN, FactSet
from app.ai.teacher_schema import Claim, ModelOutput, Note

Status = Literal["ok", "partial", "retry"]

BARE_PSEUDONYM = re.compile(r"(?<![{\w])S\d+(?![}\w])")
PSEUDONYM_ID = re.compile(r"^\{?S(\d+)\}?$")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
UUID_LIKE = re.compile(
    r"\b[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}\b", re.IGNORECASE
)
LONG_DIGITS = re.compile(r"(?<!\d)\d{10}(?!\d)")
NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(\s?%)?")


@dataclass
class GuardResult:
    kept: ModelOutput
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (where, reason)
    status: Status = "ok"
    returned: int = 0  # summary claims + notes the model returned

    @property
    def survivors(self) -> int:
        return len(self.kept.summary) + len(self.kept.notes)


def numbers(text: str) -> set[float]:
    """Every number in the text, normalised: `43%` → {43, 0.43}; digits inside `{Sn}` and
    thousands separators are ignored."""
    text = TOKEN.sub(" ", text)
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    out: set[float] = set()
    for m in NUMBER.finditer(text):
        n = float(m.group(1))
        out.add(round(n, 6))
        if m.group(2):
            out.add(round(n / 100, 6))
        elif n <= 1:
            out.add(round(n * 100, 6))
    return out


def _claim_numbers(text: str) -> list[float]:
    text = TOKEN.sub(" ", text)
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    return [round(float(m.group(1)), 6) for m in NUMBER.finditer(text)]


def _identity_leak(text: str) -> str | None:
    if BARE_PSEUDONYM.search(TOKEN.sub(" ", text)):
        return "bare pseudonym"
    if EMAIL.search(text):
        return "email"
    if UUID_LIKE.search(text):
        return "id"
    if LONG_DIGITS.search(text):
        return "long number"
    return None


def _students_of(fs: FactSet, fact_ids: list[str]) -> set[str]:
    out: set[str] = {"S1"} if fs.kind == "student" else set()
    for fid in fact_ids:
        f = fs.fact(fid)
        if f is not None:
            out |= set(f.students)
    return out


def check_claim(claim: Claim, fs: FactSet) -> tuple[Claim | None, str | None]:
    """(the kept claim with unknown ids stripped, None) or (None, why it was dropped)."""
    valid = [fid for fid in dict.fromkeys(claim.facts) if fs.fact(fid) is not None]
    if not valid:
        return None, "no valid facts cited"
    valid = valid[: lim.MAX_FACTS_PER_CLAIM]
    text = claim.text.strip()
    if not text:
        return None, "empty"
    if len(text.split()) > lim.CLAIM_WORDS * lim.OVER_LIMIT:
        return None, "too long"
    leak = _identity_leak(text)
    if leak:
        return None, leak
    allowed: set[float] = set()
    for fid in valid:
        fact = fs.fact(fid)
        assert fact is not None
        allowed |= numbers(fact.text)
    for n in _claim_numbers(text):
        if n not in allowed:
            return None, f"number {n:g} not in its facts"
    students = _students_of(fs, valid)
    for m in TOKEN.finditer(text):
        if f"S{m.group(1)}" not in students:
            return None, f"student {{S{m.group(1)}}} not in its facts"
    return Claim(text=text, facts=valid), None


def _pseudonym(raw: str) -> str | None:
    m = PSEUDONYM_ID.match(raw.strip())
    return None if m is None else f"S{m.group(1)}"


def check_note(note: Note, fs: FactSet) -> tuple[Note | None, str | None]:
    focus = note.focus.strip()
    if not focus or len(focus) > lim.FOCUS_MAX:
        return None, "focus length"
    leak = _identity_leak(focus) or ("student in focus" if TOKEN.search(focus) else None)
    if leak:
        return None, f"focus: {leak}"
    why, reason = check_claim(note.why, fs)
    if why is None:
        return None, f"why: {reason}"
    revisit = [r for r in dict.fromkeys(note.revisit) if fs.resource(r) is not None]
    if not revisit:
        return None, "no valid resource"
    group: list[str] = []
    group_facts = list(dict.fromkeys(note.group_facts))
    if fs.kind == "class" and note.group:
        if not group_facts or any(fs.fact(f) is None for f in group_facts):
            group_facts = []
        backed = _students_of(fs, group_facts) if group_facts else set()
        for raw in note.group:
            p = _pseudonym(raw)
            if p is not None and p in backed and p not in group:
                group.append(p)
    else:
        group_facts = []
    return (
        Note(
            focus=focus,
            why=why,
            revisit=revisit[: lim.MAX_REVISIT],
            group=group[: lim.MAX_GROUP],
            group_facts=group_facts if group else [],
        ),
        None,
    )


def check(output: ModelOutput, fs: FactSet) -> GuardResult:
    max_claims = (lim.CLASS_CLAIMS if fs.kind == "class" else lim.STUDENT_CLAIMS)[1]
    max_notes = lim.CLASS_NOTES if fs.kind == "class" else lim.STUDENT_NOTES
    result = GuardResult(
        kept=ModelOutput(summary=[], notes=[]),
        returned=len(output.summary) + len(output.notes),
    )
    for i, claim in enumerate(output.summary):
        if i >= max_claims:
            result.dropped.append((f"summary {i + 1}", "over the claim limit"))
            continue
        kept, reason = check_claim(claim, fs)
        if kept is None:
            result.dropped.append((f"summary {i + 1}", reason or "dropped"))
        else:
            result.kept.summary.append(kept)
    for i, note in enumerate(output.notes):
        if i >= max_notes:
            result.dropped.append((f"note {i + 1}", "over the note limit"))
            continue
        kept_note, reason = check_note(note, fs)
        if kept_note is None:
            result.dropped.append((f"note {i + 1}", reason or "dropped"))
        else:
            result.kept.notes.append(kept_note)
    if not result.dropped and result.kept.summary:
        result.status = "ok"
    elif result.kept.summary and 2 * result.survivors >= result.returned:
        result.status = "partial"
    else:
        result.status = "retry"
    return result
