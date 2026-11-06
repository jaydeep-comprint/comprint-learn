"""The teacher-summary eval's judge (spec 011): grades each surviving claim and note against the
facts it cites. Same provider as the writer (a weaker check); the guard's mechanical checks don't
depend on it."""

import json
from dataclasses import dataclass, field
from typing import Any

from app.ai.client import ChatClient
from app.ai.teacher_facts import FactSet
from app.ai.teacher_schema import ModelOutput

RUBRIC = """\
You check an AI summary written for a school teacher. You get the FACTS (numbered) and the \
summary's claims and notes, each with the fact ids it cites. Judge each one only against the facts \
it cites.

For each claim (index i):
- supported_by_cited_facts: everything the claim states follows from its cited facts.
- overclaims_cause: it states or implies a reason or cause that no cited cause fact supports \
(cause facts start with "Prerequisite" or "Repeated fails"). The reasons an at-risk fact lists \
after "is at risk:" or "At risk:" are its own stated reasons; repeating them is not an overclaim.
- vague_quantity: it uses a vague amount ("most", "many", "a few") where the facts give numbers.

For each note (index i):
- grounded: what to re-teach and why follows from the cited facts.
- actionable: a teacher could act on it tomorrow (a concrete concept, KP or prerequisite).

Return only a JSON object: {"claims": [{"i": 0, "supported_by_cited_facts": true, \
"overclaims_cause": false, "vague_quantity": false, "reason": "..."}], "notes": [{"i": 0, \
"grounded": true, "actionable": true, "reason": "..."}]}. One entry per claim and per note.
"""


@dataclass
class Grades:
    unsupported: int = 0
    overclaims: int = 0
    vague: int = 0
    claims: int = 0
    notes: int = 0
    grounded: int = 0
    actionable: int = 0
    reasons: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    unreadable: bool = False


def _claims(out: ModelOutput) -> list[dict[str, Any]]:
    return [{"text": c.text, "facts": c.facts} for c in out.summary]


async def judge(client: ChatClient, model: str, fs: FactSet, out: ModelOutput) -> Grades:
    facts = "\n".join(f"{f.id}: {f.text}" for f in fs.facts)
    payload = {
        "claims": _claims(out),
        "notes": [
            {"focus": n.focus, "why": n.why.text, "facts": n.why.facts, "revisit": n.revisit}
            for n in out.notes
        ],
    }
    data = await client.complete(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": RUBRIC},
                {
                    "role": "user",
                    "content": f"<facts>\n{facts}\n</facts>\n<summary>\n"
                    f"{json.dumps(payload, indent=1)}\n</summary>\nReply with the JSON object now.",
                },
            ],
            "max_tokens": 6000,
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "stream": False,
        }
    )
    usage = data.get("usage") or {}
    g = Grades(
        claims=len(out.summary),
        notes=len(out.notes),
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
    )
    try:
        parsed = json.loads(data["choices"][0]["message"]["content"])
        claims = list(parsed["claims"])
        notes = list(parsed.get("notes") or [])
        if len(claims) != len(out.summary):
            raise ValueError("claim count")
        for c in claims:
            g.unsupported += not bool(c["supported_by_cited_facts"])
            g.overclaims += bool(c["overclaims_cause"])
            g.vague += bool(c["vague_quantity"])
            if not c["supported_by_cited_facts"] or c["overclaims_cause"]:
                g.reasons.append(str(c.get("reason", "")))
        for n in notes:
            g.grounded += bool(n["grounded"])
            g.actionable += bool(n["actionable"])
    except (KeyError, IndexError, TypeError, ValueError):
        g.unreadable = True
    return g
