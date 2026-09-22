"""add tip submissions

Revision ID: 8f4d2c1a7b90
Revises: 770c6f1b7d8d
"""

from alembic import op
import sqlalchemy as sa


revision = "8f4d2c1a7b90"
down_revision = "770c6f1b7d8d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tip_submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("submitted_by_user_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.String(length=100), nullable=False),
        sa.Column("store_name", sa.String(length=200), nullable=False),
        sa.Column("report_start_at", sa.DateTime(), nullable=False),
        sa.Column("report_end_at", sa.DateTime(), nullable=False),
        sa.Column("total_tip_cents", sa.Integer(), nullable=False),
        sa.Column("payout_method", sa.String(length=20), nullable=False),
        sa.Column("submission_data", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tip_submissions_organization_id",
        "tip_submissions",
        ["organization_id"],
    )
    op.create_index(
        "ix_tip_submissions_submitted_by_user_id",
        "tip_submissions",
        ["submitted_by_user_id"],
    )
    op.create_index(
        "ix_tip_submissions_submitted_at",
        "tip_submissions",
        ["submitted_at"],
    )


def downgrade():
    op.drop_index("ix_tip_submissions_submitted_at", table_name="tip_submissions")
    op.drop_index("ix_tip_submissions_submitted_by_user_id", table_name="tip_submissions")
    op.drop_index("ix_tip_submissions_organization_id", table_name="tip_submissions")
    op.drop_table("tip_submissions")
