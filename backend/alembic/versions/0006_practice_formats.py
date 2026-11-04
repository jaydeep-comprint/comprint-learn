"""Practice formats: practice sessions per concept, multi-step attempt rows.

- `attempt_context` + `practice`, `session_kind` + `practice`.
- `practice_session.concept_id` (kind `practice`), its link check and one active practice per
  student × concept.
- `attempt.step` (multi-step rows share a position); unique `(session_id, position, step)`.

No new tables, so RLS is unchanged. No backfill: learned stays learned; in-progress concepts gain
the Practice step.

Revision ID: 0006_practice_formats
Revises: 0005_kp_flow
Create Date: 2026-11-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_practice_formats"
down_revision: str | Sequence[str] | None = "0005_kp_flow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KIND_LINKS_005 = (
    "(kind = 'kp') = (kp_id IS NOT NULL) AND (kind = 'remediation') = (remediation_id IS NOT NULL)"
)
KIND_LINKS_006 = KIND_LINKS_005 + " AND (kind = 'practice') = (concept_id IS NOT NULL)"
SESSION_CHECK_005 = "(context IN ('kp', 'remediation')) = (session_id IS NOT NULL)"
SESSION_CHECK_006 = "(context IN ('kp', 'remediation', 'practice')) = (session_id IS NOT NULL)"


def upgrade() -> None:
    # A value added by ALTER TYPE can't be used in the same transaction (the checks below use
    # 'practice'), so commit these first.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE attempt_context ADD VALUE IF NOT EXISTS 'practice'")
        op.execute("ALTER TYPE session_kind ADD VALUE IF NOT EXISTS 'practice'")

    op.add_column(
        "practice_session", sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_practice_session_concept_id_concept",
        "practice_session",
        "concept",
        ["concept_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_practice_session_kind_links", "practice_session", type_="check")
    op.create_check_constraint("ck_practice_session_kind_links", "practice_session", KIND_LINKS_006)
    op.create_index(
        "uq_practice_session_active_practice",
        "practice_session",
        ["student_id", "concept_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND kind = 'practice'"),
    )

    op.add_column(
        "attempt",
        sa.Column("step", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.drop_constraint("uq_attempt_session_id_position", "attempt", type_="unique")
    op.create_unique_constraint(
        "uq_attempt_session_id_position_step", "attempt", ["session_id", "position", "step"]
    )
    op.drop_constraint("ck_attempt_session_iff_practice", "attempt", type_="check")
    op.create_check_constraint("ck_attempt_session_iff_practice", "attempt", SESSION_CHECK_006)


def _shrink_enum(name: str, values: list[str], table: str, column: str) -> None:
    """Postgres can't drop enum values: recreate the type with `values` only."""
    op.execute(f"ALTER TYPE {name} RENAME TO {name}_old")
    quoted = ", ".join(f"'{v}'" for v in values)
    op.execute(f"CREATE TYPE {name} AS ENUM ({quoted})")
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {name} USING {column}::text::{name}"
    )
    op.execute(f"DROP TYPE {name}_old")


def downgrade() -> None:
    # Practice data and multi-step rows can't be represented before 0006.
    op.execute("DELETE FROM attempt WHERE context = 'practice' OR step <> 0")
    op.execute("DELETE FROM practice_session WHERE kind = 'practice'")

    # Checks and partial indexes compare the enum columns with literals, so drop them around
    # the type swaps and recreate them on the shrunken types.
    op.drop_constraint("ck_attempt_session_iff_practice", "attempt", type_="check")
    op.drop_index("uq_attempt_learn_student_item", table_name="attempt")
    _shrink_enum("attempt_context", ["learn", "kp", "remediation"], "attempt", "context")
    op.create_index(
        "uq_attempt_learn_student_item",
        "attempt",
        ["student_id", "item_id"],
        unique=True,
        postgresql_where=sa.text("context = 'learn'"),
    )
    op.create_check_constraint("ck_attempt_session_iff_practice", "attempt", SESSION_CHECK_005)
    op.drop_constraint("uq_attempt_session_id_position_step", "attempt", type_="unique")
    op.create_unique_constraint(
        "uq_attempt_session_id_position", "attempt", ["session_id", "position"]
    )
    op.drop_column("attempt", "step")

    op.drop_index("uq_practice_session_active_practice", table_name="practice_session")
    op.drop_index("uq_practice_session_active_kp", table_name="practice_session")
    op.drop_constraint("ck_practice_session_kind_links", "practice_session", type_="check")
    op.drop_constraint(
        "fk_practice_session_concept_id_concept", "practice_session", type_="foreignkey"
    )
    op.drop_column("practice_session", "concept_id")
    _shrink_enum("session_kind", ["kp", "remediation"], "practice_session", "kind")
    op.create_check_constraint("ck_practice_session_kind_links", "practice_session", KIND_LINKS_005)
    op.create_index(
        "uq_practice_session_active_kp",
        "practice_session",
        ["student_id", "kp_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND kind = 'kp'"),
    )
