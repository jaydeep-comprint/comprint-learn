"""Spec 015 security review (area 2): every link between two tenant-owned tables is a composite
foreign key that includes `org_id` on both sides, so the database itself rejects a row in one
school pointing at a row in another (see `_tenant_fk` / `_student_fk` in app/models/learning.py).
"""

import app.models  # noqa: F401 - registers every table on Base.metadata
from app.db.base import Base


def _tenant(table_name: str) -> bool:
    table = Base.metadata.tables[table_name]
    return "org_id" in table.c


def test_links_between_tenant_tables_include_org_id() -> None:
    plain = []
    for table in Base.metadata.sorted_tables:
        if "org_id" not in table.c:
            continue
        for fk in table.foreign_key_constraints:
            target = fk.referred_table
            if target.name == "organization" or "org_id" not in target.c:
                continue  # the school itself, or global content
            local = {c.name for c in fk.columns}
            remote = {e.column.name for e in fk.elements}
            if "org_id" not in local or "org_id" not in remote:
                plain.append(f"{table.name}({', '.join(sorted(local))}) -> {target.name}")
    assert not plain, f"Plain FKs between tenant tables (make them composite with org_id): {plain}"


def test_the_check_sees_the_tenant_tables() -> None:
    assert _tenant("attempt") and _tenant("practice_session") and not _tenant("item")
