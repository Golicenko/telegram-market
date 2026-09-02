"""Store Telegram-hosted training uploads and idempotent deliveries.

Revision ID: 0027_training_large_video
Revises: 0026_price_offer_listing
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0027_training_large_video"
down_revision = "0026_price_offer_listing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_inbox_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_update_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_file_id", sa.Text(), nullable=False),
        sa.Column("telegram_file_unique_id", sa.Text(), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=160), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("material_type", sa.String(length=24), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("material_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("material_type IN ('video','document')", name="ck_training_inbox_type"),
        sa.CheckConstraint("status IN ('available','attached')", name="ck_training_inbox_status"),
        sa.CheckConstraint("file_size > 0 AND file_size <= 2147483648", name="ck_training_inbox_size"),
        sa.CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="ck_training_inbox_duration"),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["material_id"], ["training_materials.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_update_id"),
    )
    op.create_index("ix_training_inbox_uploads_admin_id", "training_inbox_uploads", ["admin_id"])
    op.create_index("ix_training_inbox_uploads_file_unique_id", "training_inbox_uploads", ["telegram_file_unique_id"])
    op.create_index("ix_training_inbox_uploads_material_id", "training_inbox_uploads", ["material_id"])
    op.create_index("ix_training_inbox_uploads_status", "training_inbox_uploads", ["status"])
    op.create_index("ix_training_inbox_admin_status_created", "training_inbox_uploads", ["admin_id", "status", "created_at"])

    op.create_table(
        "training_material_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purchase_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("material_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('pending','sending','delivered','failed')", name="ck_training_material_delivery_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_training_material_delivery_attempts"),
        sa.ForeignKeyConstraint(["material_id"], ["training_materials.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_id"], ["training_purchases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("purchase_id", "material_id", name="uq_training_material_delivery_pair"),
    )
    op.create_index("ix_training_material_deliveries_purchase_id", "training_material_deliveries", ["purchase_id"])
    op.create_index("ix_training_material_deliveries_material_id", "training_material_deliveries", ["material_id"])
    op.create_index("ix_training_material_deliveries_status", "training_material_deliveries", ["status"])


def downgrade() -> None:
    op.drop_table("training_material_deliveries")
    op.drop_table("training_inbox_uploads")
