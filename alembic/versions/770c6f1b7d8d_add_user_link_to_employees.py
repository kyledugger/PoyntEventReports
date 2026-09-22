"""Add user link to employees

Revision ID: 770c6f1b7d8d
Revises: 82fe428a4c70
Create Date: 2026-09-13 02:03:39.858265

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '770c6f1b7d8d'
down_revision: Union[str, Sequence[str], None] = '82fe428a4c70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'employees',
        sa.Column(
            'user_id',
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_index(
        'ix_employees_user_id',
        'employees',
        ['user_id'],
        unique=True,
    )

    op.create_foreign_key(
        'fk_employees_user_id_users',
        'employees',
        'users',
        ['user_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_employees_user_id_users',
        'employees',
        type_='foreignkey',
    )

    op.drop_index(
        'ix_employees_user_id',
        table_name='employees',
    )

    op.drop_column(
        'employees',
        'user_id',
    )