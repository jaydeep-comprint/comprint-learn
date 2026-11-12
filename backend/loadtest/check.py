"""Spec 015 §3 pass criteria, from Locust's `<prefix>_stats.csv` and the orchestrator's summary.

- error rate < 1% (5xx, timeouts, connection errors and the scenario's own 4xx mistakes);
- p95 < 800 ms for answer submits (`POST .../answer`), p95 < 1500 ms for every other endpoint,
  p99 < 3 s overall;
- no `QueuePool limit` / pool timeout in the API log; peak DB connections ≤ workers x (pool +
  overflow).

`python -m loadtest.check out/run_stats.csv [out/summary.json]` exits 1 on any miss. The
thresholds are fixed: a miss caused only by laptop-to-Supabase round trips is reported as a
finding, never fixed by loosening this file.
"""

import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_ERROR_RATE = 0.01
ANSWER_P95_MS = 800
OTHER_P95_MS = 1500
OVERALL_P99_MS = 3000


@dataclass(frozen=True)
class Row:
    method: str
    name: str
    requests: int
    failures: int
    p50: float
    p95: float
    p99: float

    @property
    def is_answer(self) -> bool:
        return self.method == "POST" and self.name.endswith("/answer")


def _num(value: str) -> float:
    return float(value) if value not in ("", "N/A") else 0.0


def read_stats(path: Path) -> tuple[list[Row], Row]:
    rows: list[Row] = []
    total: Row | None = None
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            row = Row(
                method=r["Type"],
                name=r["Name"],
                requests=int(r["Request Count"]),
                failures=int(r["Failure Count"]),
                p50=_num(r["50%"]),
                p95=_num(r["95%"]),
                p99=_num(r["99%"]),
            )
            if r["Name"] == "Aggregated":
                total = row
            else:
                rows.append(row)
    if total is None:
        raise ValueError(f"{path}: no Aggregated row")
    return rows, total


def evaluate(rows: list[Row], total: Row, summary: dict[str, Any] | None = None) -> list[str]:
    """Every missed criterion, as a sentence (empty = pass)."""
    misses: list[str] = []
    if total.requests == 0:
        return ["no requests were made"]
    rate = total.failures / total.requests
    if rate >= MAX_ERROR_RATE:
        misses.append(f"error rate {rate:.2%} (≥ {MAX_ERROR_RATE:.0%})")
    for row in rows:
        limit = ANSWER_P95_MS if row.is_answer else OTHER_P95_MS
        if row.requests and row.p95 >= limit:
            misses.append(f"p95 {row.p95:.0f} ms ≥ {limit} ms: {row.method} {row.name}")
    if total.p99 >= OVERALL_P99_MS:
        misses.append(f"overall p99 {total.p99:.0f} ms ≥ {OVERALL_P99_MS} ms")
    if summary is not None:
        # A task exception (e.g. the answer key unreachable) isn't a request failure in Locust's
        # stats, but the scenario didn't run as written: never a pass.
        if summary.get("task_exceptions"):
            misses.append(f"{summary['task_exceptions']} Locust task exception(s)")
        if summary.get("pool_errors"):
            misses.append(f"{summary['pool_errors']} pool error line(s) in the API log")
        peak, limit_conns = summary.get("peak_db_connections"), summary.get("db_connection_limit")
        if peak is not None and limit_conns is not None and peak > limit_conns:
            misses.append(f"peak DB connections {peak} > {limit_conns}")
    return misses


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m loadtest.check <prefix>_stats.csv [summary.json]")
        return 2
    rows, total = read_stats(Path(argv[1]))
    summary = json.loads(Path(argv[2]).read_text()) if len(argv) > 2 else None
    misses = evaluate(rows, total, summary)
    print(
        f"{total.requests} requests, {total.failures} failures, "
        f"p50 {total.p50:.0f} ms, p95 {total.p95:.0f} ms, p99 {total.p99:.0f} ms"
    )
    for miss in misses:
        print(f"MISS  {miss}")
    print("PASS" if not misses else "FAIL")
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
