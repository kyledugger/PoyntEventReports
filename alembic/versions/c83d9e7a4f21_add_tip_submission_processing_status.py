"""add tip submission processing status

Revision ID: c83d9e7a4f21
Revises: b7f3c9a42e10
"""

from alembic import op
import sqlalchemy as sa


revision = "c83d9e7a4f21"
down_revision = "b7f3c9a42e10"
branch_labels = None
depends_on = None


STATUS_CHECK = "ck_tip_submissions_processing_status"


def upgrade():
    op.add_column(
        "tip_submissions",
        sa.Column(
            "processing_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "tip_submissions",
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "tip_submissions",
        sa.Column("processed_by_user_id", sa.Integer(), nullable=True),
    )

    op.create_foreign_key(
        "fk_tip_submissions_processed_by_user_id_users",
        "tip_submissions",
        "users",
        ["processed_by_user_id"],
        ["id"],
    )
    op.create_index(
        "ix_tip_submissions_processing_status",
        "tip_submissions",
        ["processing_status"],
        unique=False,
    )
    op.create_index(
        "ix_tip_submissions_processed_by_user_id",
        "tip_submissions",
        ["processed_by_user_id"],
        unique=False,
    )
    op.create_check_constraint(
        STATUS_CHECK,
        "tip_submissions",
        "processing_status IN ('pending', 'paid', 'rejected')",
    )

    # Existing cash submissions were paid when they were cashed out. Existing
    # paycheck submissions still need payroll review.
    op.execute(
        """
        UPDATE tip_submissions
        SET processing_status = 'paid',
            processed_at = submitted_at,
            processed_by_user_id = submitted_by_user_id
        WHERE payout_method = 'cash'
        """
    )

    op.alter_column(
        "tip_submissions",
        "processing_status",
        server_default=None,
    )


def downgrade():
    op.drop_constraint(STATUS_CHECK, "tip_submissions", type_="check")
    op.drop_index(
        "ix_tip_submissions_processed_by_user_id",
        table_name="tip_submissions",
    )
    op.drop_index(
        "ix_tip_submissions_processing_status",
        table_name="tip_submissions",
    )
    op.drop_constraint(
        "fk_tip_submissions_processed_by_user_id_users",
        "tip_submissions",
        type_="foreignkey",
    )
    op.drop_column("tip_submissions", "processed_by_user_id")
    op.drop_column("tip_submissions", "processed_at")
    op.drop_column("tip_submissions", "processing_status")
