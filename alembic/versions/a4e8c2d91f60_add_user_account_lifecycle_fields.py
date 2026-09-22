"""add user account lifecycle fields

Revision ID: a4e8c2d91f60
Revises: 9c7e1a4b2d90
"""

from alembic import op
import sqlalchemy as sa


revision = "a4e8c2d91f60"
down_revision = "9c7e1a4b2d90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("phone", sa.String(length=50), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
    )
    op.alter_column("users", "is_active", server_default=None)


def downgrade():
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "is_active")
    op.drop_column("users", "phone")
