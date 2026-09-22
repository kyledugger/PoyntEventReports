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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "user_security_tokens"

    # Application startup currently calls Base.metadata.create_all(). That can
    # create this table before Alembic runs, so adopt the matching table rather
    # than failing with DuplicateTable.
    if not inspector.has_table(table_name):
        op.create_table(
            table_name,
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
        existing_indexes = set()
    else:
        required_columns = {
            "id",
            "user_id",
            "purpose",
            "token_hash",
            "expires_at",
            "used_at",
            "created_at",
        }
        existing_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        missing_columns = required_columns - existing_columns
        if missing_columns:
            raise RuntimeError(
                "Existing user_security_tokens table has an unexpected "
                f"schema; missing columns: {sorted(missing_columns)}"
            )
        existing_indexes = {
            index["name"] for index in inspector.get_indexes(table_name)
        }

    indexes = (
        ("ix_user_security_tokens_user_id", ["user_id"], False),
        ("ix_user_security_tokens_purpose", ["purpose"], False),
        ("ix_user_security_tokens_token_hash", ["token_hash"], True),
    )
    for index_name, columns, unique in indexes:
        if index_name not in existing_indexes:
            op.create_index(
                index_name,
                table_name,
                columns,
                unique=unique,
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
