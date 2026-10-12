"""store empty json as sql null

Revision ID: 20ffcea30b5e
Revises: 66d1deaeece7
Create Date: 2026-10-12 21:06:53.083425

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20ffcea30b5e'
down_revision: Union[str, Sequence[str], None] = '66d1deaeece7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Old rows stored Python None as JSON 'null'; turn those into real SQL NULLs.
    bind = op.get_bind()
    for column in ("policy_flags", "ai_raw"):
        if bind.dialect.name == "postgresql":
            op.execute(f"UPDATE expenses SET {column} = NULL WHERE {column}::text = 'null'")
        else:
            op.execute(f"UPDATE expenses SET {column} = NULL WHERE {column} = 'null'")


def downgrade() -> None:
    pass  # data clean-up only; nothing to undo