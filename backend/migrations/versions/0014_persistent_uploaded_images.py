"""Store uploaded listing images in PostgreSQL.

Revision ID: 0014_persistent_images
Revises: 0013_admin_broadcasts
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0014_persistent_images"
down_revision: str | None = "0013_admin_broadcasts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("listings", "power_hp", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=False)
    op.alter_column("listings", "max_speed_kph", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=False)
    op.create_table(
        "uploaded_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="ck_uploaded_images_size_positive"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_uploaded_images_owner_id", "uploaded_images", ["owner_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_uploaded_images_owner_id", table_name="uploaded_images")
    op.drop_table("uploaded_images")
    op.alter_column("listings", "max_speed_kph", existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=False)
    op.alter_column("listings", "power_hp", existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=False)
