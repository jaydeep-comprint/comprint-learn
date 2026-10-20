"""Runs a code item's reference solution against all of its tests (validator rule 6).

Content is trusted repo code, so this is a correctness check, not a sandbox: one `python -I`
subprocess per item in a temp folder, a SIGALRM time limit per test and a hard cap per item. Results
come back through a file, so whatever the solution prints can't confuse the harness.
"""

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.content.schema import CodeAnswer

ITEM_TIMEOUT_S = 10.0

# Runs inside the subprocess: `python -I harness.py <spec.json> <code.py> <results.json>`.
HARNESS = r"""
import contextlib, io, json, math, signal, sys

class TimeLimit(BaseException):  # not Exception: a broad `except` can't swallow it
    pass

def on_alarm(signum, frame):
    raise TimeLimit()

def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.isclose(
            a, b, rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b

def lines(text):
    return [line.rstrip() for line in text.rstrip().splitlines()]

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
            report(index=i, ok=False, error=f"timed out after {spec['time_limit_ms']} ms")
            continue
        except BaseException as exc:
            signal.setitimer(signal.ITIMER_REAL, 0)
            report(index=i, ok=False, error=f"raised {type(exc).__name__}: {exc}")
            continue
        if test.get("expected_stdout") is not None:
            ok = lines(out.getvalue()) == lines(test["expected_stdout"])
            want = test["expected_stdout"].rstrip()
            error = None if ok else f"printed {out.getvalue().rstrip()!r}, expected {want!r}"
        else:
            try:
                got_json = json.loads(json.dumps(got))
            except (TypeError, ValueError):
                report(index=i, ok=False, error=f"returned {got!r}, which isn't JSON-compatible")
                continue
            ok = same(got_json, test["expected"])
            error = None if ok else f"returned {got_json!r}, expected {test['expected']!r}"
        report(index=i, ok=ok, error=error)

main()
"""


@dataclass(frozen=True)
class TestFailure:
    index: int  # -1: the code itself (didn't run, or entry missing)
    message: str


def run_tests(spec: CodeAnswer, *, source: str | None = None) -> list[TestFailure]:
    """Runs `source` (default: the reference solution) against every test; returns the failures."""
    return _run(spec, spec.solution if source is None else source, define_only=False)


def check_defines_entry(spec: CodeAnswer) -> list[TestFailure]:
    """Runs the starter code only to check that it defines `entry`."""
    return _run(spec, spec.starter, define_only=True)


def _run(spec: CodeAnswer, source: str, *, define_only: bool) -> list[TestFailure]:
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
            return [TestFailure(-1, f"took longer than {ITEM_TIMEOUT_S:g} s in total")]
        try:
            results = json.loads(results_path.read_text())
        except (FileNotFoundError, ValueError):
            stderr = proc.stderr.decode(errors="replace").strip().splitlines()
            return [
                TestFailure(
                    -1, f"the test run crashed: {stderr[-1] if stderr else proc.returncode}"
                )
            ]
    failures = [TestFailure(r["index"], r["error"]) for r in results if not r["ok"]]
    if not define_only and not failures and len(results) < len(tests):
        failures.append(TestFailure(len(results), "the test run stopped early"))
    return failures
