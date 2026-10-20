"""Walks `content/` into an in-memory `ContentBundle` (YAML parsed, schema-checked, Markdown read).

Problems found while loading (bad YAML, schema errors, missing or unreferenced files and
folders) are collected as `Issue`s on the bundle; anything that fails to parse is left out.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar

import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.content.schema import ChapterFile, ConceptFile, CourseFile, Misconception

M = TypeVar("M", bound=BaseModel)

CHAPTER_DIR = re.compile(r"^(\d{2})-(.+)$")


@dataclass(frozen=True)
class Issue:
    """One validator message: `<path>: <field path> (<id>): <message>`."""

    level: Literal["error", "warning"]
    path: str
    field: str
    id: str
    message: str

    def __str__(self) -> str:
        where = self.field
        if self.id:
            where = f"{where} ({self.id})" if where else f"({self.id})"
        return f"{self.path}: {where}: {self.message}" if where else f"{self.path}: {self.message}"


@dataclass
class LoadedConcept:
    dir: Path
    yaml_path: Path
    file: ConceptFile
    course: str
    chapter: str
    position: int
    # Referenced Markdown file name -> text (intro and worked examples).
    markdown: dict[str, str] = field(default_factory=dict)

    @property
    def qualified_id(self) -> str:
        return f"{self.course}/{self.file.id}"


@dataclass
class LoadedChapter:
    dir: Path
    yaml_path: Path
    file: ChapterFile
    position: int
    concepts: list[LoadedConcept] = field(default_factory=list)


@dataclass
class LoadedCourse:
    dir: Path
    yaml_path: Path
    file: CourseFile
    misconceptions_path: Path
    misconceptions: list[Misconception] = field(default_factory=list)
    chapters: list[LoadedChapter] = field(default_factory=list)

    @property
    def concepts(self) -> list[LoadedConcept]:
        return [c for ch in self.chapters for c in ch.concepts]


@dataclass
class ContentBundle:
    root: Path
    courses: list[LoadedCourse] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    def display(self, path: Path) -> str:
        """Paths in messages start at the content folder: `content/physics-9-10/...`."""
        try:
            return str(path.relative_to(self.root.parent))
        except ValueError:
            return str(path)

    def issue(
        self,
        level: Literal["error", "warning"],
        path: Path,
        message: str,
        *,
        field: str = "",
        id: str = "",
    ) -> None:
        self.issues.append(Issue(level, self.display(path), field, id, message))

    def error(self, path: Path, message: str, *, field: str = "", id: str = "") -> None:
        self.issue("error", path, message, field=field, id=id)

    def warning(self, path: Path, message: str, *, field: str = "", id: str = "") -> None:
        self.issue("warning", path, message, field=field, id=id)

    @property
    def concepts(self) -> list[LoadedConcept]:
        return [c for course in self.courses for c in course.concepts]


# --- YAML -----------------------------------------------------------------------------------------


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys (PyYAML silently keeps the last one)."""


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


_MISSING = object()


def _read_yaml(bundle: ContentBundle, path: Path) -> Any:
    """Parsed YAML, or `_MISSING` after recording why it couldn't be read."""
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except FileNotFoundError:
        bundle.error(path, "file is missing")
        return _MISSING
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        bundle.error(path, f"invalid YAML: {exc}".replace("\n", " "))
        return _MISSING
    if raw is None:
        bundle.error(path, "file is empty")
        return _MISSING
    return raw


# --- schema errors → issues -----------------------------------------------------------------------


def field_path(loc: tuple[int | str, ...]) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _nearest_id(raw: Any, loc: tuple[int | str, ...]) -> tuple[int, str]:
    """Length of the longest `loc` prefix pointing at a mapping with a string `id`, and the id."""
    best, best_id, node = 0, "", raw
    if isinstance(raw, dict) and isinstance(raw.get("id"), str):
        best_id = raw["id"]
    for i, part in enumerate(loc):
        try:
            node = node[part]
        except (KeyError, IndexError, TypeError):
            break
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            best, best_id = i + 1, node["id"]
    return best, best_id


_MESSAGES = {
    "extra_forbidden": "unknown key (check the spelling)",
    "missing": "is required",
}


def schema_issues(bundle: ContentBundle, path: Path, raw: Any, exc: ValidationError) -> None:
    for err in exc.errors():
        loc = tuple(err["loc"])
        cut, id_ = _nearest_id(raw, loc)
        message = _MESSAGES.get(err["type"], err["msg"]).removeprefix("Value error, ")
        rest = field_path(loc[cut:])
        bundle.error(
            path, f"{rest}: {message}" if rest else message, field=field_path(loc[:cut]), id=id_
        )


def _parse[M: BaseModel](bundle: ContentBundle, path: Path, model: type[M]) -> M | None:
    raw = _read_yaml(bundle, path)
    if raw is _MISSING:
        return None
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        schema_issues(bundle, path, raw, exc)
        return None


_MISCONCEPTIONS = TypeAdapter(list[Misconception])


def _parse_misconceptions(bundle: ContentBundle, path: Path) -> list[Misconception]:
    raw = _read_yaml(bundle, path)
    if raw is _MISSING:
        return []
    try:
        return _MISCONCEPTIONS.validate_python(raw)
    except ValidationError as exc:
        schema_issues(bundle, path, raw, exc)
        return []


# --- walking the tree -----------------------------------------------------------------------------


def load(root: Path) -> ContentBundle:
    root = root.resolve()
    bundle = ContentBundle(root=root)
    if not root.is_dir():
        bundle.error(root, "content folder not found")
        return bundle
    for course_dir in _subdirs(root):
        course_yaml = course_dir / "course.yaml"
        if not course_yaml.exists():
            bundle.warning(course_dir, "folder has no course.yaml (not a course)")
            continue
        course = _load_course(bundle, course_dir)
        if course is not None:
            bundle.courses.append(course)
    return bundle


def _subdirs(path: Path) -> list[Path]:
    return sorted(p for p in path.iterdir() if p.is_dir() and not p.name.startswith("."))


def _duplicates(ids: list[str]) -> set[str]:
    seen: set[str] = set()
    return {i for i in ids if i in seen or seen.add(i)}  # type: ignore[func-returns-value]


def _load_course(bundle: ContentBundle, course_dir: Path) -> LoadedCourse | None:
    course_yaml = course_dir / "course.yaml"
    course_file = _parse(bundle, course_yaml, CourseFile)
    if course_file is None:
        return None
    if course_file.id != course_dir.name:
        bundle.error(
            course_yaml, f"id must match the folder name {course_dir.name!r}", id=course_file.id
        )
        return None
    for dup in sorted(_duplicates(course_file.chapters)):
        bundle.error(course_yaml, f"chapter {dup!r} is listed twice", field="chapters")
    misconceptions_path = course_dir / "misconceptions.yaml"
    course = LoadedCourse(
        dir=course_dir,
        yaml_path=course_yaml,
        file=course_file,
        misconceptions_path=misconceptions_path,
        misconceptions=_parse_misconceptions(bundle, misconceptions_path),
    )

    folders: dict[str, list[Path]] = {}
    for d in _subdirs(course_dir):
        m = CHAPTER_DIR.match(d.name)
        if m is None or m.group(2) not in course_file.chapters:
            bundle.warning(d, "folder is not a chapter listed in course.yaml (ignored)")
            continue
        folders.setdefault(m.group(2), []).append(d)

    for position, chapter_id in enumerate(dict.fromkeys(course_file.chapters)):
        dirs = folders.get(chapter_id, [])
        if len(dirs) != 1:
            problem = "has no folder" if not dirs else f"has {len(dirs)} folders"
            bundle.error(
                course_yaml,
                f"chapter {chapter_id!r} {problem} (expected one named NN-{chapter_id})",
                field="chapters",
            )
            continue
        chapter = _load_chapter(bundle, course_file.id, dirs[0], chapter_id, position)
        if chapter is not None:
            course.chapters.append(chapter)

    seen: dict[str, Path] = {}
    for concept in course.concepts:
        if concept.file.id in seen:
            bundle.error(
                concept.yaml_path,
                f"concept id is also used in {bundle.display(seen[concept.file.id])}",
                id=concept.file.id,
            )
        seen.setdefault(concept.file.id, concept.yaml_path)
    return course


def _load_chapter(
    bundle: ContentBundle, course_id: str, chapter_dir: Path, chapter_id: str, position: int
) -> LoadedChapter | None:
    chapter_yaml = chapter_dir / "chapter.yaml"
    chapter_file = _parse(bundle, chapter_yaml, ChapterFile)
    if chapter_file is None:
        return None
    if chapter_file.id != chapter_id:
        bundle.error(
            chapter_yaml, f"id must match the folder name (NN-{chapter_id})", id=chapter_file.id
        )
        return None
    for dup in sorted(_duplicates(chapter_file.concepts)):
        bundle.error(chapter_yaml, f"concept {dup!r} is listed twice", field="concepts")
    chapter = LoadedChapter(
        dir=chapter_dir, yaml_path=chapter_yaml, file=chapter_file, position=position
    )

    listed = set(chapter_file.concepts)
    for d in _subdirs(chapter_dir):
        if d.name not in listed:
            bundle.warning(d, "folder is not a concept listed in chapter.yaml (ignored)")

    for i, concept_id in enumerate(dict.fromkeys(chapter_file.concepts)):
        concept_dir = chapter_dir / concept_id
        if not concept_dir.is_dir():
            bundle.error(
                chapter_yaml,
                f"concept {concept_id!r} has no folder named {concept_id}",
                field=f"concepts[{chapter_file.concepts.index(concept_id)}]",
            )
            continue
        concept = _load_concept(bundle, course_id, chapter_id, concept_dir, i)
        if concept is not None:
            chapter.concepts.append(concept)
    return chapter


def _load_concept(
    bundle: ContentBundle, course_id: str, chapter_id: str, concept_dir: Path, position: int
) -> LoadedConcept | None:
    concept_yaml = concept_dir / "concept.yaml"
    concept_file = _parse(bundle, concept_yaml, ConceptFile)
    if concept_file is None:
        return None
    if concept_file.id != concept_dir.name:
        bundle.error(concept_yaml, "id must match the folder name", id=concept_file.id)
        return None
    concept = LoadedConcept(
        dir=concept_dir,
        yaml_path=concept_yaml,
        file=concept_file,
        course=course_id,
        chapter=chapter_id,
        position=position,
    )
    refs = [("intro", "", concept_file.intro)] + [
        (f"kps[{i}].worked_example", kp.id, kp.worked_example)
        for i, kp in enumerate(concept_file.kps)
    ]
    for field_name, id_, name in refs:
        text = _read_markdown(bundle, concept, name, field_name, id_)
        if text is not None:
            concept.markdown[name] = text
    for md in sorted(concept_dir.rglob("*.md")):
        name = md.relative_to(concept_dir).as_posix()
        if name not in concept.markdown:
            bundle.warning(md, "Markdown file is not referenced from concept.yaml")
    return concept


def _read_markdown(
    bundle: ContentBundle, concept: LoadedConcept, name: str, field_name: str, id_: str
) -> str | None:
    target = (concept.dir / name).resolve()
    if not name.endswith(".md") or not target.is_relative_to(concept.dir.resolve()):
        bundle.error(
            concept.yaml_path,
            f"{name!r} must be a .md file inside the concept folder",
            field=field_name,
            id=id_,
        )
        return None
    try:
        return target.read_text(encoding="utf-8")
    except FileNotFoundError:
        bundle.error(concept.yaml_path, f"file {name!r} not found", field=field_name, id=id_)
    except (OSError, UnicodeDecodeError) as exc:
        bundle.error(concept.yaml_path, f"can't read {name!r}: {exc}", field=field_name, id=id_)
    return None
