"""make employee user link unique per organization

Revision ID: b7f3c9a42e10
Revises: a4e8c2d91f60
"""

from alembic import op
import sqlalchemy as sa


revision = "b7f3c9a42e10"
down_revision = "a4e8c2d91f60"
branch_labels = None
depends_on = None


OLD_UNIQUE_INDEX = "ix_employees_user_id"
COMPOSITE_CONSTRAINT = "uq_employees_organization_user"


def _verify_existing_user_unique_index() -> None:
    """Verify the production-shaped UNIQUE(user_id) index before dropping it."""
    inspector = sa.inspect(op.get_bind())
    for index in inspector.get_indexes("employees"):
        if index.get("name") != OLD_UNIQUE_INDEX:
            continue

        if index.get("unique") is True and index.get("column_names") == ["user_id"]:
            return

        raise RuntimeError(
            f"Found {OLD_UNIQUE_INDEX}, but it is not the expected UNIQUE(user_id) "
            "index. Stop and inspect the database schema before continuing."
        )

    raise RuntimeError(
        f"Expected employees to have unique index {OLD_UNIQUE_INDEX} on user_id, "
        "but it was not found. Stop and inspect the database schema before continuing."
    )


def upgrade():
    _verify_existing_user_unique_index()
    op.drop_index(OLD_UNIQUE_INDEX, table_name="employees")
    op.create_unique_constraint(
        COMPOSITE_CONSTRAINT,
        "employees",
        ["organization_id", "user_id"],
    )


def downgrade():
    op.drop_constraint(COMPOSITE_CONSTRAINT, "employees", type_="unique")
    op.create_index(
        OLD_UNIQUE_INDEX,
        "employees",
        ["user_id"],
        unique=True,
    )
