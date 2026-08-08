"""Add listing-bound Stars top-up intents without changing existing payments."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_listing_checkout_intents"
down_revision = "0009_training_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.add_column("star_payment_intents", sa.Column("listing_id", uuid_type, nullable=True))
    op.add_column("star_payment_intents", sa.Column("seller_id", uuid_type, nullable=True))
    op.add_column("star_payment_intents", sa.Column("deal_id", uuid_type, nullable=True))
    op.add_column("star_payment_intents", sa.Column("listing_price_af_coins", sa.Numeric(18, 2), nullable=True))
    op.add_column("star_payment_intents", sa.Column("available_balance_at_creation", sa.Numeric(18, 2), nullable=True))
    op.add_column("star_payment_intents", sa.Column("missing_af_coins", sa.Numeric(18, 2), nullable=True))
    op.add_column(
        "star_payment_intents",
        sa.Column("checkout_status", sa.String(24), nullable=False, server_default="not_requested"),
    )
    op.create_foreign_key("fk_star_intents_listing", "star_payment_intents", "listings", ["listing_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_star_intents_seller", "star_payment_intents", "users", ["seller_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_star_intents_deal", "star_payment_intents", "deals", ["deal_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_star_payment_intents_listing_id", "star_payment_intents", ["listing_id"])
    op.create_index("ix_star_payment_intents_seller_id", "star_payment_intents", ["seller_id"])
    op.create_index("ix_star_payment_intents_deal_id", "star_payment_intents", ["deal_id"])
    op.create_index("ix_star_payment_intents_checkout_status", "star_payment_intents", ["checkout_status"])
    op.drop_constraint("ck_star_payment_intent_amount", "star_payment_intents", type_="check")
    op.drop_constraint("ck_star_payment_intent_purpose", "star_payment_intents", type_="check")
    op.create_check_constraint(
        "ck_star_payment_intent_amount",
        "star_payment_intents",
        "(purpose = 'listing_checkout' AND xtr_amount >= 1) OR (purpose <> 'listing_checkout' AND xtr_amount BETWEEN 10 AND 1000)",
    )
    op.create_check_constraint(
        "ck_star_payment_intent_purpose",
        "star_payment_intents",
        "purpose IN ('topup','cart_checkout','listing_checkout')",
    )
    op.create_check_constraint(
        "ck_star_payment_intent_checkout_status",
        "star_payment_intents",
        "checkout_status IN ('not_requested','pending','completed','listing_unavailable','failed')",
    )
    op.create_check_constraint(
        "ck_star_payment_intent_missing",
        "star_payment_intents",
        "missing_af_coins IS NULL OR missing_af_coins > 0",
    )
    op.create_index(
        "uq_star_payment_intents_pending_listing",
        "star_payment_intents",
        ["user_id", "listing_id"],
        unique=True,
        postgresql_where=sa.text("purpose = 'listing_checkout' AND status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_star_payment_intents_pending_listing", table_name="star_payment_intents")
    op.drop_constraint("ck_star_payment_intent_missing", "star_payment_intents", type_="check")
    op.drop_constraint("ck_star_payment_intent_checkout_status", "star_payment_intents", type_="check")
    op.drop_constraint("ck_star_payment_intent_purpose", "star_payment_intents", type_="check")
    op.drop_constraint("ck_star_payment_intent_amount", "star_payment_intents", type_="check")
    op.create_check_constraint("ck_star_payment_intent_purpose", "star_payment_intents", "purpose IN ('topup','cart_checkout')")
    op.create_check_constraint("ck_star_payment_intent_amount", "star_payment_intents", "xtr_amount BETWEEN 10 AND 1000")
    op.drop_index("ix_star_payment_intents_checkout_status", table_name="star_payment_intents")
    op.drop_index("ix_star_payment_intents_deal_id", table_name="star_payment_intents")
    op.drop_index("ix_star_payment_intents_seller_id", table_name="star_payment_intents")
    op.drop_index("ix_star_payment_intents_listing_id", table_name="star_payment_intents")
    op.drop_constraint("fk_star_intents_deal", "star_payment_intents", type_="foreignkey")
    op.drop_constraint("fk_star_intents_seller", "star_payment_intents", type_="foreignkey")
    op.drop_constraint("fk_star_intents_listing", "star_payment_intents", type_="foreignkey")
    op.drop_column("star_payment_intents", "checkout_status")
    op.drop_column("star_payment_intents", "missing_af_coins")
    op.drop_column("star_payment_intents", "available_balance_at_creation")
    op.drop_column("star_payment_intents", "listing_price_af_coins")
    op.drop_column("star_payment_intents", "deal_id")
    op.drop_column("star_payment_intents", "seller_id")
    op.drop_column("star_payment_intents", "listing_id")
