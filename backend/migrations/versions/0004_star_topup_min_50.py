"""Allow Telegram Stars top-ups from 50 XTR."""

from alembic import op


revision = "0004_star_topup_min_50"
down_revision = "0003_payments_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_star_payment_intent_amount",
        "star_payment_intents",
        type_="check",
    )

    op.create_check_constraint(
        "ck_star_payment_intent_amount",
        "star_payment_intents",
        "xtr_amount BETWEEN 50 AND 1000",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_star_payment_intent_amount",
        "star_payment_intents",
        type_="check",
    )

    op.create_check_constraint(
        "ck_star_payment_intent_amount",
        "star_payment_intents",
        "xtr_amount BETWEEN 100 AND 1000",
    )
