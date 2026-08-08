"""Add durable training purchases, materials, delivery state and history links."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_training_library"
down_revision = "0008_training_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "training_materials",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("product_id", uuid_type, sa.ForeignKey("training_products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("material_type", sa.String(24), nullable=False),
        sa.Column("delivery_reference", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(160)),
        sa.Column("file_size", sa.BigInteger()),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("material_type IN ('text','link','photo','video','document')", name="ck_training_materials_type"),
        sa.CheckConstraint("position >= 0", name="ck_training_materials_position"),
        sa.CheckConstraint("file_size IS NULL OR file_size >= 0", name="ck_training_materials_file_size"),
    )
    op.create_index("ix_training_materials_product_id", "training_materials", ["product_id"])
    op.create_index("ix_training_materials_is_active", "training_materials", ["is_active"])
    op.create_index("ix_training_materials_product_order", "training_materials", ["product_id", "is_active", "position"])

    op.create_table(
        "training_purchases",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("product_id", uuid_type, sa.ForeignKey("training_products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("buyer_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("seller_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_type", sa.String(16), nullable=False),
        sa.Column("title_snapshot", sa.String(180), nullable=False),
        sa.Column("cover_url_snapshot", sa.Text(), nullable=False),
        sa.Column("price_af_coins", sa.Numeric(18, 2), nullable=False),
        sa.Column("seller_payout", sa.Numeric(18, 2), nullable=False),
        sa.Column("platform_commission", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("delivery_status", sa.String(24), nullable=False, server_default="not_applicable"),
        sa.Column("purchased_frozen_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("earned_frozen_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_delivery_requested_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_lock_until", sa.DateTime(timezone=True)),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("product_id", "buyer_id", name="uq_training_purchase_product_buyer"),
        sa.CheckConstraint("product_type IN ('personal','automatic')", name="ck_training_purchases_type"),
        sa.CheckConstraint("status IN ('awaiting_start','in_progress','completed')", name="ck_training_purchases_status"),
        sa.CheckConstraint("delivery_status IN ('not_applicable','pending','sending','delivered','failed')", name="ck_training_purchases_delivery_status"),
        sa.CheckConstraint("price_af_coins >= 0 AND seller_payout >= 0 AND platform_commission >= 0", name="ck_training_purchases_amounts"),
        sa.CheckConstraint("purchased_frozen_amount >= 0 AND earned_frozen_amount >= 0", name="ck_training_purchases_frozen"),
        sa.CheckConstraint("delivery_attempts >= 0", name="ck_training_purchases_delivery_attempts"),
    )
    op.create_index("ix_training_purchases_product_id", "training_purchases", ["product_id"])
    op.create_index("ix_training_purchases_buyer_id", "training_purchases", ["buyer_id"])
    op.create_index("ix_training_purchases_seller_id", "training_purchases", ["seller_id"])
    op.create_index("ix_training_purchases_product_type", "training_purchases", ["product_type"])
    op.create_index("ix_training_purchases_status", "training_purchases", ["status"])
    op.create_index("ix_training_purchases_delivery_status", "training_purchases", ["delivery_status"])
    op.create_index("ix_training_purchases_delivery_lock_until", "training_purchases", ["delivery_lock_until"])
    op.create_index("ix_training_purchases_buyer_created", "training_purchases", ["buyer_id", "created_at"])
    op.create_index("ix_training_purchases_product_status", "training_purchases", ["product_id", "status"])

    op.add_column("wallet_transactions", sa.Column("related_training_purchase_id", uuid_type, nullable=True))
    op.create_foreign_key(
        "fk_wallet_transactions_training_purchase",
        "wallet_transactions",
        "training_purchases",
        ["related_training_purchase_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_wallet_transactions_related_training_purchase_id", "wallet_transactions", ["related_training_purchase_id"])


def downgrade() -> None:
    op.drop_index("ix_wallet_transactions_related_training_purchase_id", table_name="wallet_transactions")
    op.drop_constraint("fk_wallet_transactions_training_purchase", "wallet_transactions", type_="foreignkey")
    op.drop_column("wallet_transactions", "related_training_purchase_id")
    op.drop_table("training_purchases")
    op.drop_table("training_materials")
