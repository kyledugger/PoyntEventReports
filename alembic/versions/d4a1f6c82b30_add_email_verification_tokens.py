"""add email verification and password reset tokens

Revision ID: d4a1f6c82b30
Revises: c83d9e7a4f21
"""

from alembic import op
import sqlalchemy as sa


revision = "d4a1f6c82b30"
down_revision = "c83d9e7a4f21"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_security_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_security_tokens_user_id",
        "user_security_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_security_tokens_purpose",
        "user_security_tokens",
        ["purpose"],
        unique=False,
    )
    op.create_index(
        "ix_user_security_tokens_token_hash",
        "user_security_tokens",
        ["token_hash"],
        unique=True,
    )

    # Verification begins with this deployment. Preserve access for accounts
    # that existed before it by marking them verified during the migration.
    op.execute(
        """
        UPDATE users
        SET email_verified_at = CURRENT_TIMESTAMP
        WHERE email_verified_at IS NULL
        """
    )


def downgrade():
    op.drop_index(
        "ix_user_security_tokens_token_hash",
        table_name="user_security_tokens",
    )
    op.drop_index(
        "ix_user_security_tokens_purpose",
        table_name="user_security_tokens",
    )
    op.drop_index(
        "ix_user_security_tokens_user_id",
        table_name="user_security_tokens",
    )
    op.drop_table("user_security_tokens")
