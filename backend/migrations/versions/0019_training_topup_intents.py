"""Allow exact, server-calculated Stars top-ups for training purchases.

Revision ID: 0019_training_topup
Revises: 0018_support_statuses
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0019_training_topup"
down_revision: str | None = "0018_support_statuses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_star_payment_intent_amount", "star_payment_intents", type_="check")
    op.drop_constraint("ck_star_payment_intent_purpose", "star_payment_intents", type_="check")
    op.create_check_constraint(
        "ck_star_payment_intent_amount",
        "star_payment_intents",
        "(purpose IN ('listing_checkout','training_checkout','training_topup') AND xtr_amount >= 1) "
        "OR (purpose NOT IN ('listing_checkout','training_checkout','training_topup') AND xtr_amount BETWEEN 10 AND 1000)",
    )
    op.create_check_constraint(
        "ck_star_payment_intent_purpose",
        "star_payment_intents",
        "purpose IN ('topup','cart_checkout','listing_checkout','training_checkout','training_topup')",
    )


def downgrade() -> None:
    op.execute("UPDATE star_payment_intents SET purpose = 'training_checkout' WHERE purpose = 'training_topup'")
    op.drop_constraint("ck_star_payment_intent_amount", "star_payment_intents", type_="check")
    op.drop_constraint("ck_star_payment_intent_purpose", "star_payment_intents", type_="check")
    op.create_check_constraint(
        "ck_star_payment_intent_amount",
        "star_payment_intents",
        "(purpose IN ('listing_checkout','training_checkout') AND xtr_amount >= 1) "
        "OR (purpose NOT IN ('listing_checkout','training_checkout') AND xtr_amount BETWEEN 10 AND 1000)",
    )
    op.create_check_constraint(
        "ck_star_payment_intent_purpose",
        "star_payment_intents",
        "purpose IN ('topup','cart_checkout','listing_checkout','training_checkout')",
    )
