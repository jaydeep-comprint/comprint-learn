"""`import_bundle(session, bundle, *, dry_run)`: loads validated content into Postgres.

One transaction, all-or-nothing. At each level rows are matched by slug: new ones are created,
changed ones updated (`version` + 1 when `content_hash` changes; position/parent moves don't bump
it), missing ones retired (`retired_at`), never deleted, and reappearing ones un-retired. Link rows
(`concept_prereq`, `kp_key_prereq`) are diffed to match the files. Unchanged rows aren't touched, so
a second run changes nothing.
"""

import uuid
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar, cast

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.content import hashing
from app.content.loader import ContentBundle, Issue, LoadedConcept, load
from app.content.schema import Item as ItemFile
from app.content.schema import ItemKind
from app.content.validate import has_errors, validate
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
from app.models.content import ContentMixin

R = TypeVar("R", bound=ContentMixin)

LEVELS = ("chapters", "misconceptions", "concepts", "kps", "items")
# Serialises concurrent imports (transaction-scoped advisory lock).
LOCK_KEY = 3_003_000


@dataclass
class Counts:
    created: int = 0
    updated: int = 0
    unretired: int = 0
    retired: int = 0
    unchanged: int = 0
    versions: list[int] = field(default_factory=list)

    def describe(self) -> str:
        parts = []
        if self.unchanged:
            parts.append(f"{self.unchanged} unchanged")
        if self.created:
            parts.append(f"{self.created} created")
        if self.updated:
            versions = ", ".join(f"v{v}" for v in sorted(set(self.versions)))
            parts.append(f"{self.updated} updated" + (f" ({versions})" if versions else ""))
        if self.unretired:
            parts.append(f"{self.unretired} unretired")
        if self.retired:
            parts.append(f"{self.retired} retired")
        return ", ".join(parts) or "none"

    @property
    def changed(self) -> int:
        return self.created + self.updated + self.unretired + self.retired


@dataclass
class ImportReport:
    # course slug -> level ("course", "chapters", ...) -> counts
    courses: dict[str, dict[str, Counts]] = field(default_factory=dict)
    links_changed: int = 0
    warnings: list[str] = field(default_factory=list)

    def counts(self, course: str, level: str) -> Counts:
        return self.courses.setdefault(course, {}).setdefault(level, Counts())

    @property
    def changed(self) -> int:
        rows = sum(c.changed for levels in self.courses.values() for c in levels.values())
        return rows + self.links_changed

    def lines(self) -> list[str]:
        out = []
        for slug in sorted(self.courses):
            levels = self.courses[slug]
            course = levels.get("course", Counts())
            head = f"{slug}: course {course.describe()}"
            rest = [f"{lvl} {levels[lvl].describe()}" for lvl in LEVELS if lvl in levels]
            out.append(" · ".join([head, *rest]))
        if self.links_changed:
            out.append(f"prerequisite links: {self.links_changed} changed")
        return out + [f"warning: {w}" for w in self.warnings]


@dataclass
class _Desired:
    fields: dict[str, Any]
    content_hash: str
    course: str


async def _sync[R: ContentMixin](
    session: AsyncSession,
    model: type[R],
    existing: Iterable[R],
    key_of: Callable[[R], Hashable],
    desired: dict[Hashable, _Desired],
    course_of: Callable[[R], str],
    report: ImportReport,
    level: str,
) -> dict[Hashable, R]:
    """Creates/updates/un-retires `desired` rows and retires the rest; returns active rows."""
    rows = {key_of(r): r for r in existing}
    for key, row in rows.items():
        if key not in desired and row.retired_at is None:
            row.retired_at = func.now()
            report.counts(course_of(row), level).retired += 1
    await session.flush()  # free unique slots (one active course per subject) before inserting

    active: dict[Hashable, R] = {}
    for key, want in desired.items():
        counts = report.counts(want.course, level)
        existing_row = rows.get(key)
        if existing_row is None:
            new: R = cast(Any, model)(
                id=uuid.uuid4(), content_hash=want.content_hash, version=1, **want.fields
            )
            session.add(new)
            counts.created += 1
            active[key] = new
            continue
        row = active[key] = existing_row
        changed_fields = {k: v for k, v in want.fields.items() if getattr(row, k) != v}
        for k, v in changed_fields.items():
            setattr(row, k, v)
        edited = row.content_hash != want.content_hash
        if edited:
            row.content_hash = want.content_hash
            row.version += 1
        if row.retired_at is not None:
            row.retired_at = None
            counts.unretired += 1
        elif edited or changed_fields:
            counts.updated += 1
            if edited:
                counts.versions.append(row.version)
        else:
            counts.unchanged += 1
    await session.flush()
    return active


def _item_fields(
    item: ItemFile, kind: ItemKind, concept_id: uuid.UUID, kp_id: uuid.UUID | None, position: int
) -> dict[str, Any]:
    public, answer = hashing.split_item(item)
    return {
        "slug": item.id,
        "concept_id": concept_id,
        "kp_id": kp_id,
        "kind": kind,
        "type": item.type,
        "bloom_level": item.bloom,
        "expected_minutes": Decimal(str(item.expected_minutes)),
        "has_params": item.has_params,
        "public": public,
        "answer": answer,
        "position": position,
    }


async def _all[R: ContentMixin](session: AsyncSession, model: type[R]) -> list[R]:
    return list((await session.execute(select(model))).scalars())


async def import_bundle(
    session: AsyncSession, bundle: ContentBundle, *, dry_run: bool = False
) -> ImportReport:
    """Imports a bundle in one transaction; `dry_run` rolls it back at the end.

    Callers must run `validate` first and stop on errors (`import_tree` does); only load errors
    are re-checked here.
    """
    if any(i.level == "error" for i in bundle.issues):
        raise ValueError("refusing to import content with load errors; run `app content check`")
    try:
        report = await _import(session, bundle)
    except BaseException:
        await session.rollback()
        raise
    if dry_run:
        await session.rollback()
    else:
        await session.commit()
    return report


async def _import(session: AsyncSession, bundle: ContentBundle) -> ImportReport:
    report = ImportReport()
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})

    # Courses.
    course_rows = await _all(session, Course)
    slug_by_course_id = {r.id: r.slug for r in course_rows}
    courses = await _sync(
        session,
        Course,
        course_rows,
        lambda r: r.slug,
        {
            c.file.id: _Desired(
                {
                    "slug": c.file.id,
                    "title": c.file.title,
                    "subject": c.file.subject,
                    "position": i,
                },
                hashing.course_hash(c.file),
                c.file.id,
            )
            for i, c in enumerate(bundle.courses)
        },
        lambda r: r.slug,
        report,
        "course",
    )
    slug_by_course_id |= {r.id: r.slug for r in courses.values()}
    course_id = {slug: r.id for slug, r in courses.items() if isinstance(slug, str)}

    def by_course(r: Any) -> str:
        return slug_by_course_id[r.course_id]

    # Chapters and misconceptions.
    chapters = await _sync(
        session,
        Chapter,
        await _all(session, Chapter),
        lambda r: (r.course_id, r.slug),
        {
            (course_id[c.file.id], ch.file.id): _Desired(
                {
                    "slug": ch.file.id,
                    "course_id": course_id[c.file.id],
                    "title": ch.file.title,
                    "grade": ch.file.grade,
                    "position": ch.position,
                },
                hashing.chapter_hash(ch.file),
                c.file.id,
            )
            for c in bundle.courses
            for ch in c.chapters
        },
        by_course,
        report,
        "chapters",
    )
    await _sync(
        session,
        Misconception,
        await _all(session, Misconception),
        lambda r: (r.course_id, r.slug),
        {
            (course_id[c.file.id], m.id): _Desired(
                {
                    "slug": m.id,
                    "course_id": course_id[c.file.id],
                    "title": m.title,
                    "description": m.description,
                    "position": i,
                },
                hashing.misconception_hash(m),
                c.file.id,
            )
            for c in bundle.courses
            for i, m in enumerate(c.misconceptions)
        },
        by_course,
        report,
        "misconceptions",
    )

    # Concepts.
    concept_rows = await _all(session, Concept)
    concept_files: dict[Hashable, LoadedConcept] = {
        (course_id[c.course], c.file.id): c for c in bundle.concepts
    }
    _warn_moved_concepts(report, concept_rows, concept_files, slug_by_course_id)
    concepts = await _sync(
        session,
        Concept,
        concept_rows,
        lambda r: (r.course_id, r.slug),
        {
            key: _Desired(
                {
                    "slug": c.file.id,
                    "course_id": course_id[c.course],
                    "chapter_id": chapters[(course_id[c.course], c.chapter)].id,
                    "title": c.file.title,
                    "summary": c.file.summary,
                    "intro_md": c.markdown.get(c.file.intro, ""),
                    "position": c.position,
                },
                hashing.concept_hash(c),
                c.course,
            )
            for key, c in concept_files.items()
        },
        by_course,
        report,
        "concepts",
    )
    concept_course = {r.id: slug_by_course_id[r.course_id] for r in concept_rows} | {
        r.id: slug_by_course_id[r.course_id] for r in concepts.values()
    }
    concept_by_qid = {c.qualified_id: concepts[key] for key, c in concept_files.items()}

    def by_concept(r: Any) -> str:
        return concept_course[r.concept_id]

    # Knowledge points.
    kps = await _sync(
        session,
        KnowledgePoint,
        await _all(session, KnowledgePoint),
        lambda r: (r.concept_id, r.slug),
        {
            (concepts[key].id, kp.id): _Desired(
                {
                    "slug": kp.id,
                    "concept_id": concepts[key].id,
                    "title": kp.title,
                    "worked_example_md": c.markdown.get(kp.worked_example, ""),
                    "position": i,
                },
                hashing.kp_hash(c, kp),
                c.course,
            )
            for key, c in concept_files.items()
            for i, kp in enumerate(c.file.kps)
        },
        by_concept,
        report,
        "kps",
    )

    # Items.
    desired_items: dict[Hashable, _Desired] = {}
    for key, c in concept_files.items():
        cid = concepts[key].id
        placed: list[tuple[ItemFile, ItemKind, uuid.UUID | None, int]] = [
            (c.file.misconception_check, ItemKind.misconception_check, None, 0)
        ]
        for kp in c.file.kps:
            kp_row_id = kps[(cid, kp.id)].id
            placed += [(it, ItemKind.kp_question, kp_row_id, j) for j, it in enumerate(kp.items)]
        placed += [(it, ItemKind.practice, None, j) for j, it in enumerate(c.file.practice)]
        for item, kind, kp_id, position in placed:
            desired_items[(cid, item.id)] = _Desired(
                _item_fields(item, kind, cid, kp_id, position),
                hashing.item_hash(c, item),
                c.course,
            )
    await _sync(
        session,
        Item,
        await _all(session, Item),
        lambda r: (r.concept_id, r.slug),
        desired_items,
        by_concept,
        report,
        "items",
    )

    # Link rows: diffed, not replaced, so an unchanged import writes nothing.
    edges: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}
    key_prereqs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for key, c in concept_files.items():
        cid = concepts[key].id
        for p in c.file.prereqs:
            target = p.concept if "/" in p.concept else f"{c.course}/{p.concept}"
            edges[(cid, concept_by_qid[target].id)] = Decimal(str(round(p.weight, 2)))
        for kp in c.file.kps:
            for ref in kp.key_prereqs:
                target = ref if "/" in ref else f"{c.course}/{ref}"
                key_prereqs.add((kps[(cid, kp.id)].id, concept_by_qid[target].id))
    report.links_changed += await _sync_edges(session, edges)
    report.links_changed += await _sync_key_prereqs(session, key_prereqs)
    await session.flush()
    return report


async def _sync_edges(
    session: AsyncSession, desired: dict[tuple[uuid.UUID, uuid.UUID], Decimal]
) -> int:
    changed = 0
    for row in await session.scalars(select(ConceptPrereq)):
        pair = (row.concept_id, row.prereq_id)
        if pair not in desired:
            await session.delete(row)
            changed += 1
        else:
            weight = desired.pop(pair)
            if row.encompassing_weight != weight:
                row.encompassing_weight = weight
                changed += 1
    for (concept_id, prereq_id), weight in desired.items():
        session.add(
            ConceptPrereq(concept_id=concept_id, prereq_id=prereq_id, encompassing_weight=weight)
        )
        changed += 1
    return changed


async def _sync_key_prereqs(
    session: AsyncSession, desired: set[tuple[uuid.UUID, uuid.UUID]]
) -> int:
    existing = set((await session.execute(select(KpKeyPrereq.kp_id, KpKeyPrereq.concept_id))).all())
    stale = existing - desired
    for kp_id, concept_id in stale:
        await session.execute(
            delete(KpKeyPrereq).where(
                KpKeyPrereq.kp_id == kp_id, KpKeyPrereq.concept_id == concept_id
            )
        )
    new = desired - existing
    session.add_all(KpKeyPrereq(kp_id=k, concept_id=c) for k, c in new)
    return len(stale) + len(new)


def _warn_moved_concepts(
    report: ImportReport,
    rows: list[Concept],
    files: dict[Hashable, LoadedConcept],
    slug_by_course_id: dict[uuid.UUID, str],
) -> None:
    """A concept slug that appears in a new course while retired (or retiring) in another."""
    keys = {(r.course_id, r.slug) for r in rows}
    for key, c in files.items():
        if key in keys:
            continue
        course_id = key[0]  # type: ignore[index]
        for r in rows:
            if (
                r.slug == c.file.id
                and r.course_id != course_id
                and (r.retired_at is not None or (r.course_id, r.slug) not in files)
            ):
                report.warnings.append(
                    f"concept {c.file.id!r} is new in {c.course} but was in "
                    f"{slug_by_course_id[r.course_id]} (moving courses = retire + create; "
                    "student progress does not follow)"
                )


async def import_tree(
    root: Path, sessions: async_sessionmaker[AsyncSession], *, dry_run: bool = False
) -> tuple[list[Issue], ImportReport | None]:
    """Validates `root` and, only if it has no errors, imports it. Warnings don't block."""
    bundle = load(root)
    issues = validate(bundle)
    if has_errors(issues):
        return issues, None
    async with sessions() as session:
        return issues, await import_bundle(session, bundle, dry_run=dry_run)
