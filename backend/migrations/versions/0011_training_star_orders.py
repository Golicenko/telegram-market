"""Persist Telegram-paid training orders and bind their payment intents."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_training_star_orders"
down_revision = "0010_listing_checkout_intents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.add_column("training_purchases", sa.Column("buyer_telegram_id", sa.BigInteger(), nullable=True))
    op.add_column("training_purchases", sa.Column("buyer_display_name", sa.String(256), nullable=True))
    op.add_column("training_purchases", sa.Column("buyer_username", sa.String(64), nullable=True))
    op.add_column("training_purchases", sa.Column("telegram_payment_charge_id", sa.String(255), nullable=True))
    op.execute(
        """
        UPDATE training_purchases AS purchase
        SET buyer_telegram_id = users.telegram_id,
            buyer_display_name = trim(concat_ws(' ', users.first_name, users.last_name)),
            buyer_username = users.username
        FROM users
        WHERE users.id = purchase.buyer_id
        """
    )
    op.alter_column("training_purchases", "buyer_telegram_id", nullable=False)
    op.alter_column("training_purchases", "buyer_display_name", nullable=False)
    op.create_index("ix_training_purchases_buyer_telegram_id", "training_purchases", ["buyer_telegram_id"])
    op.create_index(
        "ix_training_purchases_telegram_payment_charge_id",
        "training_purchases",
        ["telegram_payment_charge_id"],
        unique=True,
    )

    op.add_column("star_payment_intents", sa.Column("training_product_id", uuid_type, nullable=True))
    op.add_column("star_payment_intents", sa.Column("training_purchase_id", uuid_type, nullable=True))
    op.create_foreign_key(
        "fk_star_intents_training_product",
        "star_payment_intents",
        "training_products",
        ["training_product_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_star_intents_training_purchase",
        "star_payment_intents",
        "training_purchases",
        ["training_purchase_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_star_payment_intents_training_product_id", "star_payment_intents", ["training_product_id"])
    op.create_index("ix_star_payment_intents_training_purchase_id", "star_payment_intents", ["training_purchase_id"])
    op.drop_constraint("ck_star_payment_intent_amount", "star_payment_intents", type_="check")
    op.drop_constraint("ck_star_payment_intent_purpose", "star_payment_intents", type_="check")
    op.create_check_constraint(
        "ck_star_payment_intent_amount",
        "star_payment_intents",
        "(purpose IN ('listing_checkout','training_checkout') AND xtr_amount >= 1) OR "
        "(purpose NOT IN ('listing_checkout','training_checkout') AND xtr_amount BETWEEN 10 AND 1000)",
    )
    op.create_check_constraint(
        "ck_star_payment_intent_purpose",
        "star_payment_intents",
        "purpose IN ('topup','cart_checkout','listing_checkout','training_checkout')",
    )
    op.create_index(
        "uq_star_payment_intents_pending_training",
        "star_payment_intents",
        ["user_id", "training_product_id"],
        unique=True,
        postgresql_where=sa.text("purpose = 'training_checkout' AND status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_star_payment_intents_pending_training", table_name="star_payment_intents")
    op.drop_constraint("ck_star_payment_intent_purpose", "star_payment_intents", type_="check")
    op.drop_constraint("ck_star_payment_intent_amount", "star_payment_intents", type_="check")
    op.create_check_constraint(
        "ck_star_payment_intent_amount",
        "star_payment_intents",
        "(purpose = 'listing_checkout' AND xtr_amount >= 1) OR "
        "(purpose <> 'listing_checkout' AND xtr_amount BETWEEN 10 AND 1000)",
    )
    op.create_check_constraint(
        "ck_star_payment_intent_purpose",
        "star_payment_intents",
        "purpose IN ('topup','cart_checkout','listing_checkout')",
    )
    op.drop_index("ix_star_payment_intents_training_purchase_id", table_name="star_payment_intents")
    op.drop_index("ix_star_payment_intents_training_product_id", table_name="star_payment_intents")
    op.drop_constraint("fk_star_intents_training_purchase", "star_payment_intents", type_="foreignkey")
    op.drop_constraint("fk_star_intents_training_product", "star_payment_intents", type_="foreignkey")
    op.drop_column("star_payment_intents", "training_purchase_id")
    op.drop_column("star_payment_intents", "training_product_id")

    op.drop_index("ix_training_purchases_telegram_payment_charge_id", table_name="training_purchases")
    op.drop_index("ix_training_purchases_buyer_telegram_id", table_name="training_purchases")
    op.drop_column("training_purchases", "telegram_payment_charge_id")
    op.drop_column("training_purchases", "buyer_username")
    op.drop_column("training_purchases", "buyer_display_name")
    op.drop_column("training_purchases", "buyer_telegram_id")
