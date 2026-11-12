"""`make loadtest`: seed → start the API → Locust headless → check → stop the API (spec 015 §3).

    uv run --group loadtest python -m loadtest.run [--users 82] [--run-time 10m]
        [--spawn-rate 4] [--workers 1]

`--users` counts everyone: 2 teachers + the students (82 = one lab of 80). Targets the TEST
database (TEST_DATABASE_URL, from the env or backend/.env), never the dev one, and holds the
shared test-DB lock for the whole run: it refuses to start during `make test-db` (and vice versa).
The API runs on :8001 with a random per-run HS256 secret, the tutor and teacher AI off, and the
rate limiter on (a real lab must not trip it).

Writes backend/loadtest/out/: Locust CSVs, api.log (JSON lines incl. one access line per
request), summary.json (peak DB connections, pool errors, round trip, server-side time per
endpoint) and report.md (the tables for docs/loadtest/).
"""

import argparse
import asyncio
import contextlib
import json
import os
import platform
import re
import secrets
import signal
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import asyncpg
import httpx

from app.core.config import Settings
from app.testdb_lock import TestDbBusy, acquire, asyncpg_dsn
from loadtest import check

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
OUT = HERE / "out"
SEED = HERE / ".seed.json"
PORT = 8001
HOST = f"http://127.0.0.1:{PORT}"
POOL_ERRORS = re.compile(r"QueuePool limit|TimeoutError: QueuePool|pool.*timed out", re.I)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="make loadtest")
    p.add_argument("--users", type=int, default=82, help="teachers (2) + students")
    p.add_argument("--spawn-rate", type=float, default=4)
    p.add_argument("--run-time", default="10m")
    p.add_argument("--workers", type=int, default=1, help="uvicorn workers")
    return p.parse_args(argv)


def child_env(settings: Settings, secret: str) -> dict[str, str]:
    assert settings.test_database_url and settings.supabase_url
    return {
        **os.environ,
        "ENVIRONMENT": "test",
        "DATABASE_URL": settings.test_database_url,
        # From backend/.env too: Locust (tokens' issuer) and the API must agree on it.
        "SUPABASE_URL": settings.supabase_url,
        "SUPABASE_JWT_SECRET": secret,
        "TUTOR_ENABLED": "false",
        "TEACHER_AI_ENABLED": "false",
        "RATE_LIMIT_ENABLED": "true",
        "ACCESS_LOG": "true",
        "SENTRY_DSN": "",
        "LOADTEST_JWT_SECRET": secret,
        "LOADTEST_SEED": str(SEED),
        "LOADTEST_DB_URL": settings.test_database_url,
        "PYTHONPATH": str(BACKEND),
    }


def _pids(root: int) -> list[int]:
    """The API process and its children (uvicorn workers)."""
    out = subprocess.run(["pgrep", "-P", str(root)], capture_output=True, text=True).stdout
    kids = [int(p) for p in out.split()]
    return [root, *[q for k in kids for q in _pids(k)]]


def db_connections(root: int) -> int:
    """Established TCP connections from the API processes to port 5432. (Supabase's pooler
    overwrites `application_name`, so pg_stat_activity can't tell the API's connections apart.)"""
    pids = ",".join(str(p) for p in _pids(root))
    out = subprocess.run(
        ["lsof", "-nP", "-a", "-p", pids, "-iTCP:5432", "-sTCP:ESTABLISHED"],
        capture_output=True,
        text=True,
    ).stdout
    return max(0, len(out.strip().splitlines()) - 1)


async def round_trip_ms(url: str) -> float:
    dsn, connect_args = asyncpg_dsn(url)
    conn = await asyncpg.connect(dsn, timeout=30, **connect_args)
    try:
        times = []
        for _ in range(10):
            t = time.perf_counter()
            await conn.fetchval("select 1")
            times.append((time.perf_counter() - t) * 1000)
        return statistics.median(times)
    finally:
        await conn.close()


def server_times(log: Path) -> dict[str, dict[str, float]]:
    """Server-side ms per `METHOD path-template` from the API's access log lines."""
    per: dict[str, list[float]] = defaultdict(list)
    for line in log.read_text(errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("logger") == "app.access" and "ms" in rec:
            per[f"{rec['method']} {rec['path']}"].append(float(rec["ms"]))
    out = {}
    for key, values in per.items():
        values.sort()
        out[key] = {
            "n": len(values),
            "p50": values[len(values) // 2],
            "p95": values[min(len(values) - 1, int(len(values) * 0.95))],
        }
    return out


def report(args: argparse.Namespace, settings: Settings, summary: dict[str, Any]) -> str:
    rows, total = check.read_stats(OUT / "run_stats.csv")
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=BACKEND
    ).stdout.strip()
    lines = [
        f"- Commit `{commit}`, {platform.platform()}, Python {platform.python_version()}",
        f"- Users {args.users} (2 teachers), spawn {args.spawn_rate}/s, run {args.run_time}, "
        f"uvicorn workers {args.workers}, DB_POOL_SIZE {settings.db_pool_size}, "
        f"DB_MAX_OVERFLOW {settings.db_max_overflow}",
        f"- Laptop → Supabase round trip (median of 10 `select 1`): "
        f"{summary['round_trip_ms']:.0f} ms",
        f"- Peak API DB connections {summary['peak_db_connections']} "
        f"(limit {summary['db_connection_limit']}); pool errors in the log: "
        f"{summary['pool_errors']}",
        f"- Total {total.requests} requests, {total.failures} failures, p50 {total.p50:.0f} / "
        f"p95 {total.p95:.0f} / p99 {total.p99:.0f} ms",
        "",
        "| Endpoint | Requests | p50 | p95 | p99 | Failures | Server p50 / p95 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    server = summary["server_ms"]
    for r in sorted(rows, key=lambda r: -r.p95):
        key = f"{r.method} /api/v1{r.name.replace('[c]/[k]', '{course}/{concept}')}"
        s = server.get(key)
        st = f"{s['p50']:.0f} / {s['p95']:.0f}" if s else "-"
        lines.append(
            f"| {r.method} {r.name} | {r.requests} | {r.p50:.0f} | {r.p95:.0f} | {r.p99:.0f} | "
            f"{r.failures} | {st} |"
        )
    lines += ["", "Server-side time per route template (from the API's access log):", ""]
    lines += ["| Route | n | p50 ms | p95 ms |", "|---|---:|---:|---:|"]
    for key, s in sorted(server.items(), key=lambda kv: -kv[1]["p95"]):
        lines.append(f"| {key} | {s['n']:.0f} | {s['p50']:.0f} | {s['p95']:.0f} |")
    return "\n".join(lines) + "\n"


async def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if os.environ.get("ENVIRONMENT") == "production":
        print("loadtest: refusing to run with ENVIRONMENT=production", file=sys.stderr)
        return 1
    settings = Settings()
    if not settings.test_database_url or not settings.supabase_url:
        print("loadtest: TEST_DATABASE_URL and SUPABASE_URL must be set", file=sys.stderr)
        return 1
    try:
        lock = await acquire(settings.test_database_url)
    except TestDbBusy as exc:
        print(f"loadtest: {exc}", file=sys.stderr)
        return 3
    OUT.mkdir(exist_ok=True)
    secret = secrets.token_urlsafe(32)
    env = child_env(settings, secret)
    api: asyncio.subprocess.Process | None = None
    try:
        print("loadtest: seeding the test database (schema rebuild + content + LOADTEST school)")
        seed = await asyncio.create_subprocess_exec(
            *(sys.executable, "-c", "from app.cli import main; main()"),
            *("loadtest", "seed", "--out", str(SEED)),
            cwd=BACKEND,
            env=env,
        )
        if await seed.wait() != 0:
            print("loadtest: seeding failed", file=sys.stderr)
            return 1
        rtt = await round_trip_ms(settings.test_database_url)
        log_path = OUT / "api.log"
        with log_path.open("wb") as log:
            api = await asyncio.create_subprocess_exec(
                *(sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)),
                *("--workers", str(args.workers), "--log-config", str(HERE / "logging.json")),
                cwd=BACKEND,
                env=env,
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,  # its own process group: stopped together, workers too
            )
        async with httpx.AsyncClient() as client:
            for _ in range(120):
                try:
                    if (await client.get(f"{HOST}/api/v1/health")).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.5)
            else:
                print("loadtest: the API didn't become healthy (see out/api.log)", file=sys.stderr)
                return 1
        print(f"loadtest: API up on {HOST}; DB round trip {rtt:.0f} ms; starting Locust")
        locust = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "locust",
            "-f",
            str(HERE / "locustfile.py"),
            "--headless",
            "--users",
            str(args.users),
            "--spawn-rate",
            str(args.spawn_rate),
            "--run-time",
            args.run_time,
            "--host",
            HOST,
            "--csv",
            str(OUT / "run"),
            "--only-summary",
            cwd=BACKEND,
            env=env,
        )
        peak = 0
        while locust.returncode is None:
            peak = max(peak, await asyncio.to_thread(db_connections, api.pid))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(locust.wait(), timeout=2)
    finally:
        # Always stop the API, also on Ctrl-C or a failed step.
        if api is not None and api.returncode is None:
            os.killpg(api.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(api.wait(), timeout=20)
            except TimeoutError:
                os.killpg(api.pid, signal.SIGKILL)
        await lock.close()

    if locust.returncode not in (0, 1) or not (OUT / "run_stats.csv").exists():
        # 1 = Locust saw failures (judged below); anything else is a crash.
        print(f"loadtest: Locust exited with {locust.returncode} (see above)", file=sys.stderr)
        return 1
    log_text = (OUT / "api.log").read_text(errors="replace")
    summary = {
        "round_trip_ms": rtt,
        "peak_db_connections": peak,
        "db_connection_limit": args.workers * (settings.db_pool_size + settings.db_max_overflow),
        "pool_errors": len(POOL_ERRORS.findall(log_text)),
        "server_ms": server_times(OUT / "api.log"),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    (OUT / "report.md").write_text(report(args, settings, summary))
    print(f"loadtest: report in {OUT / 'report.md'}")
    return check.main(["check", str(OUT / "run_stats.csv"), str(OUT / "summary.json")])


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
