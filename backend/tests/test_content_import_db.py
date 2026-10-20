"""`app content import` on a real database: idempotency, versions, retire/un-retire, rollback."""

import copy
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text

from app.cli import DEFAULT_CONTENT_ROOT
from app.content import importer
from app.content.importer import ImportReport, import_tree
from app.content.loader import load
from app.models import (
    Chapter,
    Concept,
    ConceptPrereq,
    Course,
    Item,
    KnowledgePoint,
    KpKeyPrereq,
    Misconception,
)
from tests import content_fixtures as fx
from tests.conftest import DbApp

pytestmark = pytest.mark.db

MODELS: list[Any] = [Course, Chapter, Misconception, Concept, KnowledgePoint, Item]


async def _import(db: DbApp, root: Path, *, dry_run: bool = False) -> ImportReport:
    issues, report = await import_tree(root, db.sessions, dry_run=dry_run)
    assert report is not None, [str(i) for i in issues]
    return report


async def _snapshot(db: DbApp) -> dict[str, dict[str, tuple[int, datetime, datetime | None]]]:
    """table -> "parent/slug" -> (version, updated_at, retired_at)."""
    out: dict[str, dict[str, tuple[int, datetime, datetime | None]]] = {}
    async with db.sessions() as session:
        for model in MODELS:
            rows = (await session.execute(select(model))).scalars()
            parent = next((c for c in ("concept_id", "course_id") if hasattr(model, c)), None)
            out[model.__tablename__] = {
                f"{getattr(r, parent) if parent else ''}/{r.slug}": (
                    r.version,
                    r.updated_at,
                    r.retired_at,
                )
                for r in rows
            }
    return out


async def _count(db: DbApp, model: Any, *, active: bool = False) -> int:
    async with db.sessions() as session:
        stmt = select(func.count()).select_from(model)
        if active:
            stmt = stmt.where(model.retired_at.is_(None))
        return int(await session.scalar(stmt) or 0)


async def _item(db: DbApp, slug: str) -> Item:
    async with db.sessions() as session:
        return (await session.execute(select(Item).where(Item.slug == slug))).scalar_one()


def _write(tmp_path: Path, t: dict[str, Any], name: str = "v1") -> Path:
    return fx.write(tmp_path / name, t)


async def test_import_sample_then_again_is_a_no_op(db_app: DbApp) -> None:
    bundle = load(DEFAULT_CONTENT_ROOT)
    report = await _import(db_app, DEFAULT_CONTENT_ROOT)
    n_items = sum(
        1 + sum(len(kp.items) for kp in c.file.kps) + len(c.file.practice) for c in bundle.concepts
    )
    assert await _count(db_app, Course) == len(bundle.courses) == 3
    assert await _count(db_app, Concept) == len(bundle.concepts) == 9
    assert await _count(db_app, KnowledgePoint) == sum(len(c.file.kps) for c in bundle.concepts)
    assert await _count(db_app, Item) == n_items
    assert await _count(db_app, ConceptPrereq) == sum(len(c.file.prereqs) for c in bundle.concepts)
    assert sum(lv["items"].created for lv in report.courses.values()) == n_items

    before = await _snapshot(db_app)
    again = await _import(db_app, DEFAULT_CONTENT_ROOT)
    assert again.changed == 0
    assert all(
        c.created == c.updated == c.retired == c.unretired == 0
        for levels in again.courses.values()
        for c in levels.values()
    )
    assert await _snapshot(db_app) == before  # every updated_at identical
    assert any("unchanged" in line for line in again.lines())


async def test_edit_one_prompt_bumps_only_that_item(db_app: DbApp, tmp_path: Path) -> None:
    t = fx.tree()
    await _import(db_app, _write(tmp_path, t))
    before = await _snapshot(db_app)

    edited = copy.deepcopy(t)
    edited["maths"]["chapters"]["ch1"]["concepts"][0]["kps"][1]["items"][2]["prompt"] = (
        "Solve {{a}} x = {{b}} for x."
    )
    report = await _import(db_app, _write(tmp_path, edited, "v2"))
    assert report.changed == 1
    assert report.counts("maths", "items").versions == [2]
    assert "items 16 unchanged, 1 updated (v2)" in report.lines()[0]

    after = await _snapshot(db_app)
    changed = {
        (table, key)
        for table, rows in after.items()
        for key, value in rows.items()
        if before[table][key] != value
    }
    [(table, key)] = changed
    assert table == "item" and key.endswith("/kp2-q3")
    assert (await _item(db_app, "kp2-q3")).version == 2


async def test_remove_then_restore_an_item(db_app: DbApp, tmp_path: Path) -> None:
    t = fx.tree()
    await _import(db_app, _write(tmp_path, t))
    removed = copy.deepcopy(t)
    del removed["maths"]["chapters"]["ch1"]["concepts"][0]["kps"][0]["items"][4]
    report = await _import(db_app, _write(tmp_path, removed, "v2"))
    assert report.counts("maths", "items").retired == 1
    row = await _item(db_app, "kp1-q5")
    assert row.retired_at is not None and row.version == 1

    report = await _import(db_app, _write(tmp_path, t, "v3"))
    assert report.counts("maths", "items").unretired == 1
    row = await _item(db_app, "kp1-q5")
    assert row.retired_at is None and row.version == 1


async def test_validation_error_writes_nothing(db_app: DbApp, tmp_path: Path) -> None:
    t = fx.tree()
    t["maths"]["chapters"]["ch1"]["concepts"][0]["kps"].pop()
    issues, report = await import_tree(_write(tmp_path, t), db_app.sessions)
    assert report is None and any(i.level == "error" for i in issues)
    for model in MODELS:
        assert await _count(db_app, model) == 0


async def test_dry_run_writes_nothing(db_app: DbApp, tmp_path: Path) -> None:
    report = await _import(db_app, _write(tmp_path, fx.tree()), dry_run=True)
    assert report.counts("maths", "items").created == 17
    for model in MODELS:
        assert await _count(db_app, model) == 0


async def test_failure_mid_import_rolls_back(
    db_app: DbApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_a: object, **_k: object) -> int:
        raise ConnectionError("network dropped")

    monkeypatch.setattr(importer, "_sync_edges", boom)
    with pytest.raises(ConnectionError):
        await import_tree(_write(tmp_path, fx.tree()), db_app.sessions)
    for model in MODELS:
        assert await _count(db_app, model) == 0


async def test_deleting_a_course_folder_retires_everything(db_app: DbApp, tmp_path: Path) -> None:
    physics = fx.course("physics", "physics", concepts=[fx.concept("motion")])
    await _import(db_app, _write(tmp_path, fx.tree(fx.course(), physics)))
    report = await _import(db_app, _write(tmp_path, fx.tree(fx.course()), "v2"))
    levels = report.courses["physics"]
    assert levels["course"].retired == 1
    assert levels["concepts"].retired == 1 and levels["items"].retired == 17
    for model in MODELS:
        assert await _count(db_app, model, active=True) < await _count(db_app, model)
    assert await _count(db_app, Course) == 2  # nothing deleted


async def test_moving_and_reordering_does_not_bump_versions(db_app: DbApp, tmp_path: Path) -> None:
    t = fx.tree(fx.course(concepts=[fx.concept("a"), fx.concept("b")]))
    await _import(db_app, _write(tmp_path, t))
    moved = copy.deepcopy(t)
    c = moved["maths"]
    c["course"]["chapters"] = ["ch1", "ch2"]
    b = c["chapters"]["ch1"]["concepts"].pop()
    c["chapters"]["ch1"]["chapter"]["concepts"] = ["a"]
    c["chapters"]["ch2"] = {
        "chapter": {"id": "ch2", "title": "Two", "grade": 10, "concepts": ["b"]},
        "concepts": [b],
    }
    kps = c["chapters"]["ch1"]["concepts"][0]["kps"]
    kps.reverse()
    report = await _import(db_app, _write(tmp_path, moved, "v2"))
    assert report.counts("maths", "concepts").updated == 1
    assert report.counts("maths", "kps").updated == 2  # kp1 and kp3 swapped positions
    async with db_app.sessions() as session:
        concepts = (await session.execute(select(Concept))).scalars().all()
        assert {r.slug: r.version for r in concepts} == {"a": 1, "b": 1}
        chapter = (await session.execute(select(Chapter).where(Chapter.slug == "ch2"))).scalar_one()
        assert next(r for r in concepts if r.slug == "b").chapter_id == chapter.id
        kp_rows = (await session.execute(select(KnowledgePoint))).scalars().all()
        assert all(r.version == 1 for r in kp_rows)


async def test_links_follow_the_files(db_app: DbApp, tmp_path: Path) -> None:
    a = fx.concept("a")
    b = fx.concept("b", prereqs=[{"concept": "a", "weight": 0.5}])
    b["kps"][0]["key_prereqs"] = ["a"]
    t = fx.tree(fx.course(concepts=[a, b]))
    await _import(db_app, _write(tmp_path, t))
    assert await _count(db_app, ConceptPrereq) == 1
    assert await _count(db_app, KpKeyPrereq) == 1

    changed = copy.deepcopy(t)
    changed["maths"]["chapters"]["ch1"]["concepts"][1]["prereqs"][0]["weight"] = 0.75
    report = await _import(db_app, _write(tmp_path, changed, "v2"))
    assert report.links_changed == 1
    async with db_app.sessions() as session:
        weight = await session.scalar(text("SELECT encompassing_weight FROM concept_prereq"))
    assert float(weight) == 0.75

    # Removing concept a retires it and drops every edge that touched it.
    alone = fx.tree(fx.course(concepts=[fx.concept("b")]))
    await _import(db_app, _write(tmp_path, alone, "v3"))
    assert await _count(db_app, ConceptPrereq) == 0
    assert await _count(db_app, KpKeyPrereq) == 0
