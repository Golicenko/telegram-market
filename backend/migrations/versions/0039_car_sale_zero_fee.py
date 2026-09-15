"""Use 100% seller payout only for unsettled, fully protected car deals."""
from alembic import op

revision = "0039_car_sale_zero_fee"
down_revision = "0038_manual_gift_withdrawals"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE deals SET seller_payout = price_af_coins, platform_commission = 0
        WHERE status IN ('pending_payment','paid','seller_contacted','transfer_in_progress','buyer_confirmed','disputed')
          AND frozen_amount = price_af_coins AND frozen_amount > 0
          AND NOT EXISTS (
              SELECT 1 FROM wallet_transactions wt
              WHERE wt.related_deal_id = deals.id AND wt.transaction_type IN ('sale_income','platform_commission','purchase_completed')
          )
    """)


def downgrade():
    raise RuntimeError("Forward-only: do not reinstate old payout policy on live deals")
