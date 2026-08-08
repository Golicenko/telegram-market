"""Split spendable balances by origin without losing existing funds."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_split_wallet_balances"
down_revision = "0004_star_topup_min_50"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing available funds have no reliable provenance. Treating them as
    # purchased keeps every AF Coin spendable while preventing accidental cash-out.
    op.alter_column("wallets", "available_balance", new_column_name="purchased_balance")
    op.alter_column("wallets", "frozen_balance", new_column_name="purchased_frozen_balance")
    op.add_column("wallets", sa.Column("earned_balance", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("wallets", sa.Column("earned_frozen_balance", sa.Numeric(18, 2), nullable=False, server_default="0"))

    # Pending withdrawals are known to originate from withdrawable funds. Move
    # precisely those holds into the earned bucket and leave deal holds untouched.
    op.execute("""
        WITH pending AS (
            SELECT user_id, COALESCE(SUM(amount), 0) AS amount
            FROM withdrawal_requests
            WHERE status IN ('pending', 'approved')
            GROUP BY user_id
        )
        UPDATE wallets w
        SET earned_frozen_balance = LEAST(w.purchased_frozen_balance, p.amount),
            purchased_frozen_balance = GREATEST(w.purchased_frozen_balance - p.amount, 0)
        FROM pending p
        WHERE w.user_id = p.user_id
    """)
    op.drop_constraint("ck_wallet_nonnegative", "wallets", type_="check")
    op.create_check_constraint(
        "ck_wallet_nonnegative",
        "wallets",
        "purchased_balance >= 0 AND earned_balance >= 0 "
        "AND purchased_frozen_balance >= 0 AND earned_frozen_balance >= 0 "
        "AND total_earned >= 0",
    )
    op.add_column("star_payment_intents", sa.Column("purpose", sa.String(24), nullable=False, server_default="topup"))
    op.add_column("star_payment_intents", sa.Column("context", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_check_constraint("ck_star_payment_intent_purpose", "star_payment_intents", "purpose IN ('topup','cart_checkout')")

    op.add_column("deals", sa.Column("purchased_frozen_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("deals", sa.Column("earned_frozen_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
    # Legacy open deals used the old combined hold. Preserve them in the
    # purchased bucket; this is spend-safe and fully refundable.
    op.execute("UPDATE deals SET purchased_frozen_amount = frozen_amount WHERE status NOT IN ('completed', 'cancelled')")

    op.drop_constraint("ck_star_payment_intent_amount", "star_payment_intents", type_="check")
    op.create_check_constraint(
        "ck_star_payment_intent_amount",
        "star_payment_intents",
        "xtr_amount BETWEEN 10 AND 1000",
    )


def downgrade() -> None:
    op.drop_constraint("ck_star_payment_intent_purpose", "star_payment_intents", type_="check")
    op.drop_column("star_payment_intents", "context")
    op.drop_column("star_payment_intents", "purpose")
    op.drop_constraint("ck_star_payment_intent_amount", "star_payment_intents", type_="check")
    op.create_check_constraint("ck_star_payment_intent_amount", "star_payment_intents", "xtr_amount BETWEEN 50 AND 1000")
    op.drop_column("deals", "earned_frozen_amount")
    op.drop_column("deals", "purchased_frozen_amount")
    op.drop_constraint("ck_wallet_nonnegative", "wallets", type_="check")
    op.execute("UPDATE wallets SET purchased_balance = purchased_balance + earned_balance, purchased_frozen_balance = purchased_frozen_balance + earned_frozen_balance")
    op.drop_column("wallets", "earned_frozen_balance")
    op.drop_column("wallets", "earned_balance")
    op.alter_column("wallets", "purchased_frozen_balance", new_column_name="frozen_balance")
    op.alter_column("wallets", "purchased_balance", new_column_name="available_balance")
    op.create_check_constraint("ck_wallet_nonnegative", "wallets", "available_balance >= 0 AND frozen_balance >= 0 AND total_earned >= 0")
