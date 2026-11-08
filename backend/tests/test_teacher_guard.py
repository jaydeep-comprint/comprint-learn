"""The citation guard for teacher summaries (spec 011)."""

import uuid

from app.ai.teacher_facts import Fact, FactSet, Resource
from app.ai.teacher_guard import check, check_claim, numbers
from app.ai.teacher_schema import Claim, ModelOutput, Note

FS = FactSet(
    kind="class",
    window="7d",
    facts=[
        Fact("F1", "class", "25 students in scope.", [], {}),
        Fact(
            "F2",
            "weak_concept",
            "Concept 'Linear equations' (chapter 'Algebra 2'): 6 of 14 KP tries failed (43%) "
            "by 5 students; 3 stuck now; 40% learned (last 7 days).",
            [],
            {},
        ),
        Fact(
            "F3",
            "cause_now",
            "Prerequisite 'Integers' is the open cause for 3 students stuck in 'Linear equations' "
            "({S1}, {S3} and {S10}): 2 brushing up, 1 relearning.",
            ["S1", "S3", "S10"],
            {},
        ),
        Fact("F4", "hints", "Class: 0.21 hints per question (last 7 days).", [], {}),
    ],
    resources=[Resource("R1", "lesson", "Integers", "maths/int", "Integers")],
    pseudonyms={f"S{i}": uuid.UUID(int=i) for i in (1, 3, 10)},
)


def _claim(text: str, *facts: str) -> Claim:
    return Claim(text=text, facts=list(facts))


def kept(text: str, *facts: str) -> bool:
    return check_claim(_claim(text, *facts), FS)[0] is not None


def reason(text: str, *facts: str) -> str | None:
    return check_claim(_claim(text, *facts), FS)[1]


def test_numbers_normalised() -> None:
    assert numbers("43%") == {43.0, 0.43}
    assert numbers("0.43") == {0.43, 43.0}
    assert numbers("1 of 3") == {1.0, 3.0}
    assert numbers("6/14 and 6 of 14") == {6.0, 14.0}
    assert numbers("{S10} chose it") == set()
    assert numbers("1,200 answers") == {1200.0}


def test_facts_must_exist() -> None:
    assert reason("Linear equations is weak.", "F99") == "no valid facts cited"
    assert reason("Linear equations is weak.") == "no valid facts cited"
    claim, _ = check_claim(_claim("Linear equations is weak.", "F99", "F2"), FS)
    assert claim is not None and claim.facts == ["F2"]


def test_number_checks() -> None:
    assert kept("43% of KP tries on Linear equations failed.", "F2")
    assert kept("6 of 14 tries failed.", "F2")
    assert kept("6/14 tries failed.", "F2")
    assert kept("About 43 % failed.", "F2")
    assert kept("Hints run at 21% of questions.", "F4")  # 0.21 = 21%
    assert kept("Algebra 2 is the chapter.", "F2")  # a number inside a cited title
    assert reason("9 of 14 tries failed.", "F2") == "number 9 not in its facts"
    assert reason("25 students are in scope and 6 failed.", "F1") == "number 6 not in its facts"
    assert kept("25 students are in scope and 6 failed.", "F1", "F2")
    # "1 of 3" doesn't license "100%": only decimal rates get the x100 form.
    assert reason("100% of the 3 stuck students relearn.", "F3") == "number 100 not in its facts"


def test_student_tokens() -> None:
    assert kept("{S1} and {S10} are stuck on Integers.", "F3")
    assert reason("{S2} is stuck.", "F3") == "student {S2} not in its facts"
    assert reason("{S1} is weak.", "F2") == "student {S1} not in its facts"
    assert reason("S3 is stuck on Integers.", "F3") == "bare pseudonym"
    assert reason("Email asha@example.com about it.", "F3") == "email"
    assert reason(f"Student {uuid.UUID(int=1)} is stuck.", "F3") == "id"
    assert reason("Call 9876543210 today.", "F3") == "long number"


def test_word_limit() -> None:
    long = " ".join(["word"] * 61)
    assert reason(long, "F1") == "too long"
    assert kept(" ".join(["word"] * 60), "F1")


def _note(**kw: object) -> Note:
    base: dict[str, object] = {
        "focus": "Integers before linear equations",
        "why": {"text": "Integers is the open cause for 3 students.", "facts": ["F3"]},
        "revisit": ["R1"],
        "group": ["S1", "S3"],
        "group_facts": ["F3"],
    }
    base.update(kw)
    return Note.model_validate(base)


def _out(*claims: Claim, notes: list[Note] | None = None) -> ModelOutput:
    return ModelOutput(summary=list(claims), notes=notes or [])


GOOD = _claim("Linear equations: 43% of KP tries failed.", "F2")


def test_note_rules() -> None:
    r = check(_out(GOOD, GOOD, notes=[_note()]), FS)
    assert r.status == "ok"
    assert r.kept.notes[0].group == ["S1", "S3"]

    r = check(_out(GOOD, GOOD, notes=[_note(revisit=["R9"])]), FS)
    assert r.kept.notes == [] and ("note 1", "no valid resource") in r.dropped

    r = check(_out(GOOD, GOOD, notes=[_note(group=["S1", "S2", "{S10}"])]), FS)
    assert r.kept.notes[0].group == ["S1", "S10"]  # S2 isn't in group_facts' students

    r = check(_out(GOOD, GOOD, notes=[_note(group_facts=["F3", "F99"])]), FS)
    assert r.kept.notes[0].group == []  # every group fact must be valid

    r = check(_out(GOOD, GOOD, notes=[_note(focus="x" * 81)]), FS)
    assert r.kept.notes == []


def test_student_note_has_no_group_and_s1_is_implicit() -> None:
    fs = FactSet(
        kind="student",
        window="7d",
        facts=[Fact("F1", "kp_fails", "KP 'Moving terms': failed 2 of 3 tries.", ["S1"], {})],
        resources=[Resource("R1", "worked_example", "Moving terms", "maths/c1", "C1", "k1")],
        pseudonyms={"S1": uuid.UUID(int=1)},
    )
    out = ModelOutput(
        summary=[Claim(text="{S1} failed 2 of 3 tries on Moving terms.", facts=["F1"])],
        notes=[
            Note(
                focus="Moving terms",
                why=Claim(text="{S1} failed 2 tries.", facts=["F1"]),
                revisit=["R1"],
                group=["S1"],
                group_facts=["F1"],
            )
        ],
    )
    r = check(out, fs)
    assert r.status == "ok"
    assert r.kept.notes[0].group == []


def test_status_thresholds() -> None:
    bad = _claim("8 students failed.", "F2")
    assert check(_out(GOOD, GOOD), FS).status == "ok"
    assert check(_out(GOOD, bad), FS).status == "partial"  # 1 of 2 survives
    assert check(_out(GOOD, bad, bad), FS).status == "retry"  # 1 of 3
    assert check(_out(bad, bad), FS).status == "retry"
    six = check(_out(*[GOOD] * 6), FS)
    assert len(six.kept.summary) == 5 and six.status == "partial"
