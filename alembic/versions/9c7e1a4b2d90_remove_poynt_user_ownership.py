"""make Poynt connections organization-owned only

Revision ID: 9c7e1a4b2d90
Revises: 8f4d2c1a7b90
"""

from alembic import op
import sqlalchemy as sa

revision = "9c7e1a4b2d90"
down_revision = "8f4d2c1a7b90"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = {column["name"] for column in inspector.get_columns("poynt_connections")}
    if "user_id" not in columns:
        return

    # organization_id is already the authoritative owner from the staged
    # organization migration. Refuse to remove the legacy column if any row
    # somehow lost its organization mapping.
    unmapped = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM poynt_connections "
            "WHERE organization_id IS NULL"
        )
    ).scalar_one()
    if unmapped:
        raise RuntimeError(
            f"Cannot remove poynt_connections.user_id: {unmapped} "
            "connection(s) have no organization_id."
        )

    # Dropping the column also removes PostgreSQL indexes/constraints that are
    # owned by the column, but explicitly remove the known legacy index first
    # so this migration is clear about the old ownership model.
    bind.execute(
        sa.text(
            "DROP INDEX IF EXISTS ix_poynt_connections_user_id"
        )
    )

    # The staged migration left the old user_id foreign key in place. The
    # default PostgreSQL name is used by SQLAlchemy for this original FK.
    bind.execute(
        sa.text(
            "ALTER TABLE poynt_connections "
            "DROP CONSTRAINT IF EXISTS poynt_connections_user_id_fkey"
        )
    )

    op.drop_column("poynt_connections", "user_id")


def downgrade():
    # The old user_id ownership cannot be reconstructed safely from the new
    # organization-owned model. Restore the nullable column only; do not guess
    # which user should own a connection.
    op.add_column(
        "poynt_connections",
        sa.Column("user_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_poynt_connections_user_id",
        "poynt_connections",
        ["user_id"],
        unique=True,
    )
    op.create_foreign_key(
        "poynt_connections_user_id_fkey",
        "poynt_connections",
        "users",
        ["user_id"],
        ["id"],
    )
