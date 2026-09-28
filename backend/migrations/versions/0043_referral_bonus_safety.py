"""Registration-only attribution and non-withdrawable referral funds.

Revision ID: 0043_referral_bonus_safety
Revises: 0042_referral_program
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0043_referral_bonus_safety"
down_revision = "0042_referral_program"
branch_labels = None
depends_on = None


def upgrade():
    # Coordinate with in-flight old-version transactions before the preflight.
    # Deployment must quiesce old workers; see the release checklist.
    op.execute(
        "LOCK TABLE users, wallets, wallet_transactions, referral_rewards IN ACCESS EXCLUSIVE MODE"
    )
    # Old releases credited rewards to earned_balance. Never guess the origin of
    # already spent/reserved/withdrawn money. Abort atomically if it needs review.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM (
              SELECT r.user_id, SUM(r.amount) amount, MIN(t.created_at) first_reward
              FROM referral_rewards r JOIN wallet_transactions t ON t.id=r.transaction_id
              GROUP BY r.user_id
            ) r LEFT JOIN wallets w ON w.user_id=r.user_id
            WHERE w.id IS NULL OR w.earned_balance < r.amount OR w.total_earned < r.amount
              OR EXISTS (
                SELECT 1 FROM wallet_transactions t
                WHERE t.user_id=r.user_id AND t.created_at >= r.first_reward
                  AND (t.available_after < t.available_before OR t.frozen_after != t.frozen_before)
              )
          ) THEN
            RAISE EXCEPTION 'REFERRAL_LEGACY_REVIEW_REQUIRED: legacy rewards were spent or reserved. Run scripts/audit_referral_legacy.py; reconcile provenance before upgrading. No funds have been changed.';
          END IF;
        END $$;
    """)
    op.add_column(
        "users",
        sa.Column(
            "referral_candidate_at_registration",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # A legacy candidate was not captured exclusively on INSERT, so cannot prove
    # a new account. Existing relationships and their audit records are retained.
    op.execute(
        "UPDATE users SET pending_referral_code=NULL, referral_registration_processed=true"
    )
    for column in ("bonus_balance", "bonus_frozen_balance"):
        op.add_column(
            "wallets",
            sa.Column(column, sa.Numeric(18, 2), nullable=False, server_default="0"),
        )
    op.create_check_constraint(
        "ck_wallet_bonus_nonnegative",
        "wallets",
        "bonus_balance >= 0 AND bonus_frozen_balance >= 0",
    )
    for table in ("deals", "training_purchases"):
        op.add_column(
            table,
            sa.Column(
                "bonus_frozen_amount",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
        )
        op.create_check_constraint(
            f"ck_{table}_bonus_nonnegative", table, "bonus_frozen_amount >= 0"
        )
    op.add_column(
        "wallet_transactions",
        sa.Column(
            "balance_breakdown",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    # Safe case only: every earlier reward is provably still in the earned bucket.
    # Preserve total available funds and append an audit entry, never rewrite one.
    op.execute("""
        WITH rewards AS (SELECT user_id, SUM(amount) amount FROM referral_rewards GROUP BY user_id),
        moved AS (
          UPDATE wallets w SET earned_balance=w.earned_balance-r.amount,
            bonus_balance=r.amount, total_earned=w.total_earned-r.amount, version=w.version+1
          FROM rewards r WHERE w.user_id=r.user_id RETURNING w.*
        )
        INSERT INTO wallet_transactions (id,user_id,transaction_type,amount,available_before,available_after,
          frozen_before,frozen_after,description,external_reference,balance_breakdown)
        SELECT md5('referral-bonus-migration:'||user_id::text)::uuid,user_id,'referral_bonus_reclassified',0,
          purchased_balance+earned_balance+bonus_balance,purchased_balance+earned_balance+bonus_balance,
          purchased_frozen_balance+earned_frozen_balance,purchased_frozen_balance+earned_frozen_balance,
          'Реферальные AF переведены в невыводимый бонусный баланс',
          'referral-bonus-migration:'||user_id::text,
          jsonb_build_object('bonus_balance',bonus_balance::text,'earned_balance',earned_balance::text,
            'purchased_balance',purchased_balance::text,'reclassified',bonus_balance::text)
        FROM moved;
    """)


def downgrade():
    raise RuntimeError(
        "Bonus provenance is financial history. Use a reviewed forward migration."
    )
