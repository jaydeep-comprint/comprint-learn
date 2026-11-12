"""Spec 015: the per-process content cache reloads exactly when the content stamp changes."""

from typing import Any

import pytest

from app.content import cache


class _Result:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self.row = row

    def one(self) -> tuple[Any, ...]:
        return self.row


class _Sync:
    def __init__(self) -> None:
        self.info: dict[str, Any] = {}


class FakeSession:
    """Just what `cache` uses: `execute` for the stamp and `sync_session.info`."""

    def __init__(self, stamp: tuple[Any, ...]) -> None:
        self.stamp = stamp
        self.stamp_queries = 0
        self.sync_session = _Sync()

    async def execute(self, _stmt: Any) -> _Result:
        self.stamp_queries += 1
        return _Result(self.stamp)


@pytest.fixture(autouse=True)
def _empty_cache() -> None:
    cache.clear()


async def test_same_stamp_reuses_the_value_and_checks_once_per_transaction() -> None:
    loads = 0

    async def load() -> list[int]:
        nonlocal loads
        loads += 1
        return [1, 2, 3]

    session = FakeSession(("2026-11-12", 24))
    first = await cache.cached(session, "graph", load)  # type: ignore[arg-type]
    second = await cache.cached(session, "graph", load)  # type: ignore[arg-type]
    assert first is second and loads == 1
    assert session.stamp_queries == 1  # remembered for the transaction
    other = FakeSession(("2026-11-12", 24))  # another request, same content
    assert await cache.cached(other, "graph", load) is first  # type: ignore[arg-type]
    assert loads == 1


async def test_an_import_changes_the_stamp_and_reloads() -> None:
    values = iter(["old", "new"])

    async def load() -> str:
        return next(values)

    assert await cache.cached(FakeSession(("t1", 24)), "graph", load) == "old"  # type: ignore[arg-type]
    assert await cache.cached(FakeSession(("t2", 25)), "graph", load) == "new"  # type: ignore[arg-type]


def test_the_stamp_is_forgotten_when_a_transaction_ends() -> None:
    sync = _Sync()
    sync.info["content_stamp"] = ("t1",)
    cache._forget_stamp(sync, None)
    assert "content_stamp" not in sync.info


def test_stamp_covers_every_content_table() -> None:
    sql = str(cache.STAMP_SQL)
    for table in (
        "course",
        "chapter",
        "concept",
        "knowledge_point",
        "item",
        "misconception",
        "concept_prereq",
        "kp_key_prereq",
    ):
        assert f"FROM {table}" in sql
