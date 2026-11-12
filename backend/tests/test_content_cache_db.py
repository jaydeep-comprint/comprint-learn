"""Spec 015 review: the cached course graph survives a rollback in the request that filled it
(it holds plain values, never session-bound ORM rows)."""

import pytest

from app.api.deps import OrgScope
from app.content import cache
from app.services import learn
from tests.conftest import DbApp
from tests.learn_helpers import world

pytestmark = pytest.mark.db


async def test_cached_graph_outlives_a_rollback_and_its_session(db_app: DbApp) -> None:
    w = await world(db_app)
    cache.clear()
    async with db_app.sessions() as session:
        graph = await learn._graph(OrgScope.system(session, w.a.org_id))
        await session.rollback()  # expires every ORM row loaded in this session
    # Another request, after the first session closed: the cached values still read fine.
    async with db_app.sessions() as session:
        again = await learn._graph(OrgScope.system(session, w.a.org_id))
    assert again is graph
    course = graph.courses["physics-9-10"]
    assert (course.slug, course.subject.value) == ("physics-9-10", "physics")
    assert all(ch.title and ch.position >= 0 for ch in graph.chapters.values())
