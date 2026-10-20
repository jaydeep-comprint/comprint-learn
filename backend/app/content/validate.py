"""`validate(bundle) -> list[Issue]`: validator rules 1-7 of spec 003.

1 schema (loader) · 2 references · 3 graph · 4 structure · 5 answer self-consistency ·
6 code reference solutions · 7 retire safety (a removed concept is a missing reference, rule 2).
"""

import ast
import os
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import sympy

from app.content.code_runner import check_defines_entry, run_tests
from app.content.hashing import item_texts
from app.content.loader import ContentBundle, Issue, LoadedConcept, image_refs, link_refs
from app.content.params import (
    RESERVED,
    ExpressionError,
    SampleError,
    Value,
    evaluate,
    param_values,
    parse,
    placeholders,
    render,
    sample,
)
from app.content.schema import (
    Bloom,
    CodeAnswer,
    ExpressionAnswer,
    Item,
    ItemKind,
    ItemType,
    McqAnswer,
    MultistepAnswer,
    NumericAnswer,
)
from app.content.units import UnitError, parse_unit

__all__ = ["Issue", "validate"]

SEEDS = 50
MIN_SATISFIED = 48  # constraints must hold on >= 95% of seeds
MIN_DISTINCT_PROMPTS = 5
MIN_POOL, GOOD_POOL = 6, 8
MAX_MCQ_SHARE = 0.3
IMAGE_EXTENSIONS = {".svg", ".png", ".webp", ".jpg"}
MAX_IMAGE_BYTES = 500 * 1024
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
# SVGs ship same-origin, so anything that can run script or navigate is rejected: scripts, event
# handlers, links/hrefs other than #fragments, animation that can rewrite attributes, embedded
# HTML and character entities (which can hide `javascript:`).
SVG_ACTIVE = re.compile(
    r"<script|\son[a-z]+\s*=|javascript:|<foreignObject|<a[\s>]|<animate|<set[\s>]|<iframe|<embed"
    r"|<object|&#|href\s*=\s*[\"'](?!#)",
    re.IGNORECASE,
)
BLOCKED_MODULES = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "pathlib",
    "io",
    "urllib",
    "http",
    "ftplib",
    "smtplib",
    "ctypes",
    "multiprocessing",
    "threading",
    "asyncio",
    "signal",
    "importlib",
    "builtins",
    "pickle",
    "tempfile",
    "glob",
}
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class _Where:
    path: Path
    field: str
    id: str


@dataclass
class _CodeJob:
    where: _Where
    spec: CodeAnswer


@dataclass
class _Validator:
    bundle: ContentBundle
    run_code: bool
    issues: list[Issue] = field(default_factory=list)
    code_jobs: list[_CodeJob] = field(default_factory=list)
    checked_images: set[Path] = field(default_factory=set)

    def report(
        self, level: Literal["error", "warning"], where: _Where | Path, message: str
    ) -> None:
        if isinstance(where, Path):
            where = _Where(where, "", "")
        self.issues.append(
            Issue(level, self.bundle.display(where.path), where.field, where.id, message)
        )

    def error(self, where: _Where | Path, message: str) -> None:
        self.report("error", where, message)

    def warning(self, where: _Where | Path, message: str) -> None:
        self.report("warning", where, message)


def validate(bundle: ContentBundle, *, run_code: bool = True) -> list[Issue]:
    """Every issue in the bundle: loader issues first, then rules 2-7, ordered by file."""
    v = _Validator(bundle, run_code)
    concepts = {c.qualified_id: c for c in bundle.concepts}
    _check_courses(v)
    for concept in bundle.concepts:
        _check_concept(v, concept, concepts)
    _check_cycles(v, concepts)
    if run_code:
        _run_code_jobs(v)
    order = {p: i for i, p in enumerate(dict.fromkeys(i.path for i in bundle.issues + v.issues))}
    return sorted(bundle.issues + v.issues, key=lambda i: order[i.path])


def has_errors(issues: list[Issue], *, strict: bool = False) -> bool:
    return any(i.level == "error" or strict for i in issues)


# --- courses --------------------------------------------------------------------------------------


def _check_courses(v: _Validator) -> None:
    by_subject: dict[str, str] = {}
    for course in v.bundle.courses:
        f = course.file
        other = by_subject.setdefault(f.subject.value, f.id)
        if other != f.id:
            v.error(
                _Where(course.yaml_path, "subject", f.id),
                f"subject {f.subject.value} is already used by course {other!r} "
                "(one course per subject)",
            )
        seen: set[str] = set()
        for i, m in enumerate(course.misconceptions):
            if m.id in seen:
                v.error(_Where(course.misconceptions_path, f"[{i}]", m.id), "duplicate id")
            seen.add(m.id)


# --- concepts -------------------------------------------------------------------------------------


def _resolve(ref: str, course: str) -> str:
    return ref if "/" in ref else f"{course}/{ref}"


def _items(concept: LoadedConcept) -> Iterator[tuple[str, Item, ItemKind]]:
    f = concept.file
    yield "misconception_check", f.misconception_check, ItemKind.misconception_check
    for i, kp in enumerate(f.kps):
        for j, item in enumerate(kp.items):
            yield f"kps[{i}].items[{j}]", item, ItemKind.kp_question
    for k, item in enumerate(f.practice):
        yield f"practice[{k}]", item, ItemKind.practice


def _check_concept(
    v: _Validator, concept: LoadedConcept, concepts: dict[str, LoadedConcept]
) -> None:
    f, path = concept.file, concept.yaml_path

    # Rule 2/3: prerequisite edges.
    direct: set[str] = set()
    for i, p in enumerate(f.prereqs):
        where = _Where(path, f"prereqs[{i}]", f.id)
        target = _resolve(p.concept, concept.course)
        if target == concept.qualified_id:
            v.error(where, "a concept can't be its own prerequisite")
        elif target not in concepts:
            v.error(where, f"unknown concept {p.concept!r}")
        elif target in direct:
            v.error(where, f"duplicate prerequisite {p.concept!r}")
        if not 0 < p.weight <= 1 or round(p.weight, 2) != p.weight:
            v.error(where, "weight must be > 0 and <= 1, with at most 2 decimals")
        direct.add(target)

    # Rule 4: structure.
    if not 3 <= len(f.kps) <= 4:
        v.error(_Where(path, "kps", f.id), f"a concept needs 3-4 KPs (found {len(f.kps)})")
    kp_ids = Counter(kp.id for kp in f.kps)
    for i, kp in enumerate(f.kps):
        where = _Where(path, f"kps[{i}]", kp.id)
        if kp_ids[kp.id] > 1:
            v.error(where, "duplicate KP id in this concept")
        for ref in kp.key_prereqs:
            if _resolve(ref, concept.course) not in direct:
                v.error(where, f"key prereq {ref!r} is not one of this concept's direct prereqs")
        _check_pool(v, where, kp.items)

    if f.misconception_check.bloom not in (Bloom.remember, Bloom.understand):
        v.error(
            _Where(path, "misconception_check", f.misconception_check.id),
            "bloom must be remember or understand (Learn layer)",
        )
    if not f.practice:
        v.error(_Where(path, "practice", f.id), "needs at least 1 practice item")
    for k, item in enumerate(f.practice):
        if item.type not in (ItemType.multistep, ItemType.code):
            v.error(
                _Where(path, f"practice[{k}]", item.id), "practice items must be multistep or code"
            )

    item_ids = Counter(item.id for _, item, _ in _items(concept))
    misconceptions = _course_misconceptions(v.bundle, concept.course)
    for field_path, item, _ in _items(concept):
        where = _Where(path, field_path, item.id)
        if item_ids[item.id] > 1:
            v.error(where, "duplicate item id in this concept (item ids are per concept)")
        _check_item(v, where, item, misconceptions)
        for text in item_texts(item):
            _check_refs(v, where, concept, text or "")

    # Rule 2: Markdown references.
    for name, text in concept.markdown.items():
        _check_refs(v, concept.dir / name, concept, text)
    _check_asset_folder(v, concept)


def _course_misconceptions(bundle: ContentBundle, course_id: str) -> set[str]:
    for course in bundle.courses:
        if course.file.id == course_id:
            return {m.id for m in course.misconceptions}
    return set()


def _check_pool(v: _Validator, where: _Where, items: list[Item]) -> None:
    weight = sum(2 if item.has_params else 1 for item in items)
    if weight < MIN_POOL:
        v.error(
            where,
            f"question pool is too small: weight {weight}, needs >= {MIN_POOL} "
            "(fixed item = 1, param item = 2)",
        )
    elif weight < GOOD_POOL:
        v.warning(where, f"question pool weight is {weight}; aim for >= {GOOD_POOL}")
    mcqs = sum(item.type == ItemType.mcq for item in items)
    if items and mcqs / len(items) > MAX_MCQ_SHARE:
        v.warning(where, f"{mcqs} of {len(items)} questions are MCQ; use MCQ sparingly (<= 30%)")


def _check_refs(v: _Validator, where: _Where | Path, concept: LoadedConcept, text: str) -> None:
    root = concept.dir.resolve()
    for ref in image_refs(text):
        parsed = urlparse(ref)
        if parsed.scheme or parsed.netloc or ref.startswith("/"):
            v.error(where, f"image {ref!r} must be a relative path inside the concept folder")
            continue
        target = (concept.dir / ref).resolve()
        if not target.is_relative_to(root):
            v.error(where, f"image {ref!r} must stay inside the concept folder")
        elif not _served_path(target.relative_to(root).as_posix()):
            # frontend/vite/content-assets.ts serves only these paths.
            v.error(
                where,
                f"image {ref!r} must live in the concept's img/ folder (names: A-Z a-z 0-9 . _ -)",
            )
        elif target.suffix.lower() not in IMAGE_EXTENSIONS:
            v.error(where, f"image {ref!r} must be .svg, .png, .webp or .jpg")
        elif not target.is_file():
            v.error(where, f"image {ref!r} not found")
        else:
            v.checked_images.add(target)  # the img/ folder scan skips it
            if target.stat().st_size > MAX_IMAGE_BYTES:
                v.error(where, f"image {ref!r} is larger than 500 KB")
            elif target.suffix.lower() == ".svg" and SVG_ACTIVE.search(
                target.read_text(errors="replace")
            ):
                v.error(where, f"image {ref!r} contains scripts or event handlers")
    for ref in link_refs(text):
        parsed = urlparse(ref)
        if not parsed.scheme:
            continue
        if parsed.scheme != "https" or parsed.hostname not in YOUTUBE_HOSTS:
            v.error(where, f"link {ref!r}: external links must be https YouTube links")


SERVED_ASSET = re.compile(r"img(/[A-Za-z0-9_-][A-Za-z0-9._-]*)+")


def _served_path(rel: str) -> bool:
    return SERVED_ASSET.fullmatch(rel) is not None


def _check_asset_folder(v: _Validator, concept: LoadedConcept) -> None:
    """Every image under img/ ships to the CDN (vite/content-assets.ts), referenced or not."""
    for path in sorted((concept.dir / "img").rglob("*")):
        if (
            not path.is_file()
            or path.suffix.lower() not in IMAGE_EXTENSIONS
            or path.resolve() in v.checked_images
        ):
            continue
        if path.stat().st_size > MAX_IMAGE_BYTES:
            v.error(path, "image is larger than 500 KB")
        elif path.suffix.lower() == ".svg" and SVG_ACTIVE.search(path.read_text(errors="replace")):
            v.error(path, "SVG contains scripts, links, event handlers or entities")


# --- graph ----------------------------------------------------------------------------------------


def _check_cycles(v: _Validator, concepts: dict[str, LoadedConcept]) -> None:
    edges = {
        qid: [
            t
            for p in c.file.prereqs
            if (t := _resolve(p.concept, c.course)) in concepts and t != qid
        ]
        for qid, c in concepts.items()
    }
    state: dict[str, int] = {}  # 1 = on the stack, 2 = done
    stack: list[str] = []
    found: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in edges[node]:
            if state.get(nxt) == 1:
                cycle = stack[stack.index(nxt) :]
                start = cycle.index(min(cycle))
                found.add(tuple(cycle[start:] + cycle[:start]))
            elif nxt not in state:
                visit(nxt)
        stack.pop()
        state[node] = 2

    for node in sorted(edges):
        if node not in state:
            visit(node)
    for cycle in sorted(found):
        concept = concepts[cycle[0]]
        v.error(
            _Where(concept.yaml_path, "prereqs", concept.file.id),
            "prerequisite cycle: " + " → ".join([*cycle, cycle[0]]),
        )


# --- items ----------------------------------------------------------------------------------------


def _expression_names(text: str | int | float) -> set[str]:
    return set(NAME.findall(text)) if isinstance(text, str) else set()


def _check_item(v: _Validator, where: _Where, item: Item, misconceptions: set[str]) -> None:
    names = set(item.params) | set(item.derived)
    for name in sorted(names & RESERVED):
        v.error(where, f"{name!r} is a built-in function or constant; pick another name")
    for name in sorted(set(item.params) & set(item.derived)):
        v.error(where, f"{name!r} is both a param and a derived value")

    # {{placeholders}} and unused params.
    templates = [t for t in item_texts(item) if t]
    used: set[str] = set()
    for text in templates:
        for name in placeholders(text):
            used.add(name)
            if name not in names:
                v.error(where, f"unknown placeholder {{{{{name}}}}}")
    for expr in [*item.constraints, *item.derived.values(), *_answer_values(item)]:
        used |= _expression_names(expr)
    for name in item.params:
        if name not in used:
            v.warning(where, f"param {name!r} is never used")

    for name, spec in item.params.items():
        try:
            param_values(spec)
        except ExpressionError as exc:
            v.error(where, f"param {name}: {exc}")
            return

    _check_spec_static(v, where, item, misconceptions)
    if item.type == ItemType.code:
        if item.params:
            v.error(where, "code items can't use params")
        assert isinstance(item.spec, CodeAnswer)
        v.code_jobs.append(_CodeJob(where, item.spec))
        return
    _check_seeds(v, where, item)


def _answer_values(item: Item) -> list[str | int | float]:
    spec = item.spec
    specs = [s.answer.spec for s in spec.steps] if isinstance(spec, MultistepAnswer) else [spec]
    return [s.value for s in specs if isinstance(s, NumericAnswer | ExpressionAnswer)]


def _check_spec_static(v: _Validator, where: _Where, item: Item, misconceptions: set[str]) -> None:
    spec = item.spec
    if isinstance(spec, MultistepAnswer):
        if not 2 <= len(spec.steps) <= 10:
            v.error(where, f"a multistep item needs 2-10 steps (found {len(spec.steps)})")
        for i, step in enumerate(spec.steps):
            _check_answer_static(v, where, step.answer.spec, misconceptions, prefix=f"steps[{i}]: ")
    elif isinstance(spec, CodeAnswer):
        if len(spec.tests) < 3:
            v.error(where, f"a code item needs >= 3 tests (found {len(spec.tests)})")
        if not any(t.visible for t in spec.tests):
            v.error(where, "a code item needs at least 1 visible test")
        for label, source in (("starter", spec.starter), ("solution", spec.solution)):
            for problem in _import_problems(source):
                v.error(where, f"{label}: {problem}")
    else:
        _check_answer_static(v, where, spec, misconceptions)


def _check_answer_static(
    v: _Validator,
    where: _Where,
    spec: NumericAnswer | ExpressionAnswer | McqAnswer,
    misconceptions: set[str],
    *,
    prefix: str = "",
) -> None:
    def err(message: str) -> None:
        v.error(where, prefix + message)

    if isinstance(spec, NumericAnswer):
        if spec.unit is not None:
            try:
                parse_unit(spec.unit)
            except UnitError as exc:
                err(str(exc))
        if spec.mode == "sigfig":
            if spec.sigfigs is None:
                err("sigfigs is required when mode is sigfig")
            elif not 1 <= spec.sigfigs <= 6:
                err("sigfigs must be 1-6")
        elif spec.sigfigs is not None:
            err("sigfigs only applies when mode is sigfig")
        if spec.mode == "tolerance":
            if (spec.rel_tol is None) == (spec.abs_tol is None):
                err("mode tolerance needs exactly one of rel_tol or abs_tol")
            elif spec.rel_tol is not None and not 0 < spec.rel_tol <= 0.2:
                err("rel_tol must be > 0 and <= 0.2")
            elif spec.abs_tol is not None and not spec.abs_tol > 0:
                err("abs_tol must be > 0")
        elif spec.rel_tol is not None or spec.abs_tol is not None:
            err("rel_tol/abs_tol only apply when mode is tolerance")
    elif isinstance(spec, ExpressionAnswer):
        if not spec.variables:
            err("an expression answer needs at least one variable")
        if len(set(spec.variables)) != len(spec.variables):
            err("variables must be unique")
    else:
        if not 2 <= len(spec.options) <= 5:
            err(f"an MCQ needs 2-5 options (found {len(spec.options)})")
        ids = [o.id for o in spec.options]
        if len(set(ids)) != len(ids):
            err("option ids must be unique")
        correct = [o for o in spec.options if o.correct]
        if len(correct) != 1:
            err(f"an MCQ needs exactly one correct option (found {len(correct)})")
        for o in spec.options:
            if o.misconception is not None and o.misconception not in misconceptions:
                err(f"option {o.id}: unknown misconception {o.misconception!r}")
            if o.correct and o.misconception is not None:
                err(f"option {o.id}: the correct option can't carry a misconception")
        if not any(o.misconception for o in spec.options if not o.correct):
            err("tag at least one distractor with a misconception")


def _import_problems(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"syntax error on line {exc.lineno}: {exc.msg}"]
    problems = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        for module in modules:
            top = module.split(".")[0]
            if top in BLOCKED_MODULES or top not in sys.stdlib_module_names:
                problems.append(f"import {module} isn't allowed (standard library only, no I/O)")
    return problems


# --- rule 5: per-seed self-consistency ------------------------------------------------------------


def _check_seeds(v: _Validator, where: _Where, item: Item) -> None:
    seeds = range(SEEDS) if item.has_params else range(1)
    satisfied = 0
    prompts: set[str] = set()
    reported: set[str] = set()
    renders = True

    def once(key: str, message: str) -> None:
        if key not in reported:
            reported.add(key)
            v.error(where, message)

    for seed in seeds:
        try:
            values = sample(item, seed)
        except SampleError:
            continue
        except ExpressionError as exc:
            satisfied += 1  # the constraints held; a derived value failed
            once("derived", f"seed {seed}: {exc}")
            continue
        satisfied += 1
        try:
            prompts.add(render(item.prompt, values))
        except KeyError:
            renders = False  # reported as an unknown placeholder
        spec = item.spec
        if isinstance(spec, MultistepAnswer):
            for i, step in enumerate(spec.steps):
                _check_answer_values(once, step.answer.spec, values, seed, prefix=f"steps[{i}]: ")
        elif isinstance(spec, NumericAnswer | ExpressionAnswer):
            _check_answer_values(once, spec, values, seed)

    if item.has_params:
        if satisfied == 0:
            v.error(where, "constraints are never satisfied")
        elif satisfied < MIN_SATISFIED:
            v.error(
                where,
                f"constraints hold for only {satisfied} of {SEEDS} seeds (need >= {MIN_SATISFIED})",
            )
        elif renders and not reported and len(prompts) < MIN_DISTINCT_PROMPTS:
            v.error(
                where,
                f"params give only {len(prompts)} distinct prompts over {SEEDS} seeds "
                f"(need >= {MIN_DISTINCT_PROMPTS})",
            )


def _is_finite_decimal(x: Value) -> bool:
    if not isinstance(x, sympy.Rational):
        return False
    q = int(x.q)
    for p in (2, 5):
        while q % p == 0:
            q //= p
    return q == 1


def _check_answer_values(
    once: Callable[[str, str], None],
    spec: NumericAnswer | ExpressionAnswer | McqAnswer,
    values: dict[str, Value],
    seed: int,
    *,
    prefix: str = "",
) -> None:
    if isinstance(spec, NumericAnswer):
        try:
            x = evaluate(spec.value, values)
        except ExpressionError as exc:
            once(prefix + "value", f"{prefix}seed {seed}: answer value {exc}")
            return
        if spec.mode == "sigfig" and x == 0:
            once(prefix + "zero", f"{prefix}seed {seed}: value is 0, which has no sig figs")
        if spec.mode == "exact" and not _is_finite_decimal(x):
            once(
                prefix + "exact",
                f"{prefix}seed {seed}: value {x} is not a finite decimal; "
                "use mode sigfig or tolerance",
            )
    elif isinstance(spec, ExpressionAnswer):
        names = {k: sympy.sympify(val) for k, val in values.items()}
        clash = set(spec.variables) & set(names)
        if clash:
            once(prefix + "clash", f"{prefix}variables {sorted(clash)} clash with params/derived")
            return
        names.update({var: sympy.Symbol(var) for var in spec.variables})
        try:
            expr = parse(spec.value, names)
        except ExpressionError as exc:
            once(prefix + "parse", f"{prefix}expression: {exc}")
            return
        if not isinstance(expr, sympy.Expr):
            once(prefix + "parse", f"{prefix}expression {spec.value!r} is not an expression")
        elif expr.has(sympy.zoo, sympy.nan, sympy.oo, -sympy.oo):
            once(prefix + "finite", f"{prefix}seed {seed}: expression is not finite")


# --- rule 6: code reference solutions -------------------------------------------------------------


def _run_code_jobs(v: _Validator) -> None:
    def run(job: _CodeJob) -> list[str]:
        problems = [
            f"solution: {f.message}" if f.index < 0 else f"test {f.index}: {f.message}"
            for f in run_tests(job.spec)
        ]
        problems += [f"starter: {f.message}" for f in check_defines_entry(job.spec)]
        return problems

    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as pool:
        for job, problems in zip(v.code_jobs, pool.map(run, v.code_jobs), strict=True):
            for problem in problems:
                v.error(job.where, problem)
