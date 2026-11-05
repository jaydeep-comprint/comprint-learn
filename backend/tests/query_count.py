"""Count SQL statements run on the app's engine (the dashboard's fixed-query-count tests)."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event

from app.db.session import get_engine


@dataclass
class Counter:
    n: int = 0


@contextmanager
def count_queries() -> Iterator[Counter]:
    counter = Counter()
    engine = get_engine().sync_engine

    def on_execute(*_args: Any, **_kw: Any) -> None:
        counter.n += 1

    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)
