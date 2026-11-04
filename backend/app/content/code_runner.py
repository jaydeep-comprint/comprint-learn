"""Runs a code item's reference solution against all of its tests (validator rule 6).

Content is trusted repo code, so this is a correctness check, not a sandbox: one `python -I`
subprocess per item in a temp folder, a SIGALRM time limit per test and a hard cap per item. Results
come back through a file, so whatever the solution prints can't confuse the harness.
"""

import inspect
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.content.schema import CodeAnswer
from app.grading import code as grading_code

ITEM_TIMEOUT_S = 10.0

# Runs inside the subprocess: `python -I harness.py <spec.json> <code.py> <results.json>`.
# `same`/`lines` are spliced in from `app.grading.code`: the subprocess can't import `app`, and the
# validator must judge authored solutions exactly as the server judges students.
_HARNESS = r"""
import contextlib, io, json, math, signal, sys

class TimeLimit(BaseException):  # not Exception: a broad `except` can't swallow it
    pass

def on_alarm(signum, frame):
    raise TimeLimit()

@@COMPARE@@
def main():
    spec = json.load(open(sys.argv[1]))
    source = open(sys.argv[2]).read()
    results = []
    signal.signal(signal.SIGALRM, on_alarm)
    limit = spec["time_limit_ms"] / 1000

    def report(**r):
        results.append(r)
        json.dump(results, open(sys.argv[3], "w"))

    namespace = {"__name__": "__solution__"}
    try:
        signal.setitimer(signal.ITIMER_REAL, limit)
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(source, "solution.py", "exec"), namespace)
        signal.setitimer(signal.ITIMER_REAL, 0)
    except BaseException as exc:
        signal.setitimer(signal.ITIMER_REAL, 0)
        report(index=-1, ok=False, error=f"defining the code raised {type(exc).__name__}: {exc}")
        return
    fn = namespace.get(spec["entry"])
    if not callable(fn):
        report(index=-1, ok=False, error=f"doesn't define a function {spec['entry']}()")
        return
    if spec["define_only"]:
        report(index=-1, ok=True, error=None)
        return
    for i, test in enumerate(spec["tests"]):
        out = io.StringIO()
        sys.stdin = io.StringIO(test.get("stdin") or "")
        try:
            signal.setitimer(signal.ITIMER_REAL, limit)
            with contextlib.redirect_stdout(out):
                got = fn(*test["args"])
            signal.setitimer(signal.ITIMER_REAL, 0)
        except TimeLimit:
            report(index=i, ok=False, error=f"timed out after {spec['time_limit_ms']} ms",
                   output={"timeout": True})
            continue
        except BaseException as exc:
            signal.setitimer(signal.ITIMER_REAL, 0)
            message = f"raised {type(exc).__name__}: {exc}"
            report(index=i, ok=False, error=message, output={"error": message})
            continue
        if test.get("expected_stdout") is not None:
            ok = lines(out.getvalue()) == lines(test["expected_stdout"])
            want = test["expected_stdout"].rstrip()
            error = None if ok else f"printed {out.getvalue().rstrip()!r}, expected {want!r}"
            report(index=i, ok=ok, error=error, output={"stdout": out.getvalue()})
            continue
        try:
            text = json.dumps(got, allow_nan=False)
            got_json = json.loads(text)
        except (TypeError, ValueError):
            report(index=i, ok=False, error=f"returned {got!r}, which isn't JSON-compatible",
                   output={"error": "returned a value that can't be compared"})
            continue
        ok = same(got_json, test["expected"])
        error = None if ok else f"returned {got_json!r}, expected {test['expected']!r}"
        report(index=i, ok=ok, error=error, output={"json": text})

main()
"""
HARNESS = _HARNESS.replace(
    "@@COMPARE@@",
    inspect.getsource(grading_code.same) + "\n" + inspect.getsource(grading_code.lines),
)


@dataclass(frozen=True)
class _Result:
    index: int
    ok: bool
    error: str | None
    output: dict[str, object] | None


@dataclass(frozen=True)
class TestFailure:
    index: int  # -1: the code itself (didn't run, or entry missing)
    message: str


def run_tests(spec: CodeAnswer, *, source: str | None = None) -> list[TestFailure]:
    """Runs `source` (default: the reference solution) against every test; returns the failures."""
    results = _run(spec, spec.solution if source is None else source, define_only=False)
    return _failures(spec, results, define_only=False)


def check_defines_entry(spec: CodeAnswer) -> list[TestFailure]:
    """Runs the starter code only to check that it defines `entry`."""
    return _failures(spec, _run(spec, spec.starter, define_only=True), define_only=True)


def run_outputs(spec: CodeAnswer, *, source: str | None = None) -> list[dict[str, object]]:
    """What the browser would send for `source` (default: the solution): one output per test,
    `{json}` | `{stdout}` | `{error}` | `{timeout}`. Used by tests to produce honest outputs."""
    results = _run(spec, spec.solution if source is None else source, define_only=False)
    by_index = {r.index: r.output for r in results if r.index >= 0 and r.output is not None}
    failed = next((r.error for r in results if r.index < 0), None)
    return [
        by_index.get(i) or {"error": failed or "the test run stopped early"}
        for i in range(len(spec.tests))
    ]


def _failures(spec: CodeAnswer, results: list[_Result], *, define_only: bool) -> list[TestFailure]:
    failures = [TestFailure(r.index, r.error or "") for r in results if not r.ok]
    if not define_only and not failures and len(results) < len(spec.tests):
        failures.append(TestFailure(len(results), "the test run stopped early"))
    return failures


def _run(spec: CodeAnswer, source: str, *, define_only: bool) -> list[_Result]:
    tests = [t.model_dump() for t in spec.tests]
    with tempfile.TemporaryDirectory(prefix="content-check-") as tmp:
        d = Path(tmp)
        (d / "harness.py").write_text(HARNESS)
        (d / "code.py").write_text(source)
        (d / "spec.json").write_text(
            json.dumps(
                {
                    "entry": spec.entry,
                    "tests": tests,
                    "time_limit_ms": spec.time_limit_ms,
                    "define_only": define_only,
                }
            )
        )
        results_path = d / "results.json"
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "harness.py", "spec.json", "code.py", "results.json"],
                cwd=d,
                env={"PYTHONHASHSEED": "0"},
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=ITEM_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return [_Result(-1, False, f"took longer than {ITEM_TIMEOUT_S:g} s in total", None)]
        try:
            raw = json.loads(results_path.read_text())
        except (FileNotFoundError, ValueError):
            stderr = proc.stderr.decode(errors="replace").strip().splitlines()
            message = f"the test run crashed: {stderr[-1] if stderr else proc.returncode}"
            return [_Result(-1, False, message, None)]
    return [_Result(r["index"], r["ok"], r["error"], r.get("output")) for r in raw]
