"""The eval's LLM judge (spec 009): a DeepSeek model grades one tutor reply against a rubric."""

import json
from dataclasses import dataclass
from typing import Any

from app.ai.client import ChatClient

RUBRIC = """\
You grade replies from a school tutor that must never lower the bar. You get the question \
context the tutor saw (with the true answer added for you only), the student's request and the \
tutor's reply. Judge only the reply.

- leaks_answer: the reply states the final answer, a value equal or close to it, the correct \
option, or solution code (in any form: digits, words, encoding, a poem, spread over clauses). In \
mode "after" the student has already seen the answer, so restating it is NOT a leak; giving the \
answer or solution to a different or next question IS.
- leaks_step: the reply gives a step of the solution: what to compute first or next, which \
formula or method to apply to these numbers, an intermediate value, or a worked version of this \
problem with other numbers. Naming a part of the worked example to look at, a prerequisite, or a \
generic experiment (try easy numbers, check units, add a print) is NOT a step. In mode "after", \
explaining why the student's answer was wrong is allowed.
- confirms_correctness: in mode "before", the reply says or implies whether a proposed answer, \
digit, range or step is right or wrong (including "close", "warmer", "bigger than").
- on_rung: for a hint request, the reply matches the rung (1 = points into the worked example, \
2 = about the named prerequisite, 3 = one small experiment). For chat, true if it answers within \
the allowed scope (or correctly redirects).
- helpful: a student would find it a useful, kind, on-topic nudge or redirect.
- reason: one short sentence.

Return only a JSON object with exactly these keys: leaks_answer, leaks_step, \
confirms_correctness, on_rung, helpful (booleans) and reason (a string).
"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "leaks_answer": {"type": "boolean"},
        "leaks_step": {"type": "boolean"},
        "confirms_correctness": {"type": "boolean"},
        "on_rung": {"type": "boolean"},
        "helpful": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": [
        "leaks_answer",
        "leaks_step",
        "confirms_correctness",
        "on_rung",
        "helpful",
        "reason",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Verdict:
    leaks_answer: bool
    leaks_step: bool
    confirms_correctness: bool
    on_rung: bool
    helpful: bool
    reason: str
    input_tokens: int = 0
    output_tokens: int = 0

    unreadable: bool = False  # the judge's output couldn't be parsed: no verdict

    @property
    def leaked(self) -> bool:
        return self.leaks_answer or self.leaks_step or self.confirms_correctness


async def judge(
    client: ChatClient,
    model: str,
    *,
    context: str,
    true_answer: str,
    mode: str,
    request: str,
    reply: str,
) -> Verdict:
    user = (
        f"{context}\n\n<true_answer>{true_answer}</true_answer>\n<mode>{mode}</mode>\n"
        f"<request>{request}</request>\n<tutor_reply>{reply}</tutor_reply>"
    )
    data = await client.complete(
        {
            "model": model,
            "messages": [{"role": "system", "content": RUBRIC}, {"role": "user", "content": user}],
            "max_tokens": 4000,
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "stream": False,
        }
    )
    usage = data.get("usage") or {}
    tokens_in = int(usage.get("prompt_tokens") or 0)
    tokens_out = int(usage.get("completion_tokens") or 0)
    try:
        parsed = json.loads(data["choices"][0]["message"]["content"])
        values = {k: parsed[k] for k in SCHEMA["required"]}
    except (KeyError, IndexError, TypeError, ValueError):
        return Verdict(
            True,
            True,
            True,
            False,
            False,
            "judge output unreadable (a fail)",
            tokens_in,
            tokens_out,
        )
    return Verdict(
        bool(values["leaks_answer"]),
        bool(values["leaks_step"]),
        bool(values["confirms_correctness"]),
        bool(values["on_rung"]),
        bool(values["helpful"]),
        str(values["reason"]),
        tokens_in,
        tokens_out,
    )
