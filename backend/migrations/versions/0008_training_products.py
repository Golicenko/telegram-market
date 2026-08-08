"""Add premium training products without deleting legacy accounts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_training_products"
down_revision = "0007_mobile_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "training_products",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("admin_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("short_description", sa.String(360), nullable=False),
        sa.Column("full_description", sa.Text(), nullable=False),
        sa.Column("cover_url", sa.Text(), nullable=False),
        sa.Column("promo_video_url", sa.Text()),
        sa.Column("product_type", sa.String(16), nullable=False),
        sa.Column("price_af_coins", sa.Numeric(18, 2), nullable=False),
        sa.Column("availability", sa.String(24), nullable=False, server_default="available"),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("product_type IN ('personal','automatic')", name="ck_training_products_type"),
        sa.CheckConstraint("availability IN ('available','unavailable','coming_soon')", name="ck_training_products_availability"),
        sa.CheckConstraint("price_af_coins >= 0", name="ck_training_products_price"),
    )
    op.create_index("ix_training_products_admin_id", "training_products", ["admin_id"])
    op.create_index("ix_training_products_product_type", "training_products", ["product_type"])
    op.create_index("ix_training_products_published", "training_products", ["published"])
    op.create_index("ix_training_products_pinned", "training_products", ["pinned"])
    op.create_index("ix_training_products_deleted_at", "training_products", ["deleted_at"])
    op.create_index("ix_training_products_public_order", "training_products", ["published", "pinned", "created_at"])
    # account_listings is intentionally preserved for rollback/audit.


def downgrade() -> None:
    op.drop_table("training_products")
