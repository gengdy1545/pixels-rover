"""store gateway user ids as opaque strings

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-23 00:00:00.000000

Kratos identity ids are opaque strings, not application integers. Keep the
existing column names but widen the type so ownership filters continue to work
without coupling assistant-service to an identity-provider implementation.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("analysis_sessions") as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.Integer(),
            type_=sa.String(length=128),
            existing_nullable=False,
        )
    with op.batch_alter_table("conversation_threads") as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.Integer(),
            type_=sa.String(length=128),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("analysis_sessions") as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.String(length=128),
            type_=sa.Integer(),
            existing_nullable=False,
        )
    with op.batch_alter_table("conversation_threads") as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.String(length=128),
            type_=sa.Integer(),
            existing_nullable=False,
        )
