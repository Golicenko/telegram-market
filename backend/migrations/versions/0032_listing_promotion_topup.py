"""Allow exact shortfall top-ups for listing promotion.

Revision ID: 0032_listing_promotion_topup
Revises: 0031_price_offer_message_link
"""

from alembic import op


revision = "0032_listing_promotion_topup"
down_revision = "0031_price_offer_message_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_star_payment_intent_amount", "star_payment_intents", type_="check")
    op.drop_constraint("ck_star_payment_intent_purpose", "star_payment_intents", type_="check")
    op.create_check_constraint(
        "ck_star_payment_intent_purpose",
        "star_payment_intents",
        "purpose IN ('topup','cart_checkout','listing_checkout','training_checkout','training_topup','listing_promotion_topup')",
    )
    op.create_check_constraint(
        "ck_star_payment_intent_amount",
        "star_payment_intents",
        "(purpose IN ('listing_checkout','training_checkout','training_topup','listing_promotion_topup') AND xtr_amount >= 1) OR "
        "(purpose NOT IN ('listing_checkout','training_checkout','training_topup','listing_promotion_topup') AND xtr_amount BETWEEN 10 AND 1000)",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE star_payment_intents SET purpose = 'training_topup' "
        "WHERE purpose = 'listing_promotion_topup'"
    )
    op.drop_constraint("ck_star_payment_intent_amount", "star_payment_intents", type_="check")
    op.drop_constraint("ck_star_payment_intent_purpose", "star_payment_intents", type_="check")
    op.create_check_constraint(
        "ck_star_payment_intent_purpose",
        "star_payment_intents",
        "purpose IN ('topup','cart_checkout','listing_checkout','training_checkout','training_topup')",
    )
    op.create_check_constraint(
        "ck_star_payment_intent_amount",
        "star_payment_intents",
        "(purpose IN ('listing_checkout','training_checkout','training_topup') AND xtr_amount >= 1) OR "
        "(purpose NOT IN ('listing_checkout','training_checkout','training_topup') AND xtr_amount BETWEEN 10 AND 1000)",
    )
