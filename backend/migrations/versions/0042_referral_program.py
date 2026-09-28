"""Persistent referral attribution, rewards and native share cache.

Revision ID: 0042_referral_program
Revises: 0041_seller_delivery_deadline
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0042_referral_program"
down_revision = "0041_seller_delivery_deadline"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("referral_code", sa.String(8)))
    op.create_unique_constraint("uq_users_referral_code", "users", ["referral_code"])
    op.add_column("users", sa.Column("pending_referral_code", sa.String(8)))
    # Existing accounts must never qualify as new referrals, including bot-only accounts.
    op.add_column(
        "users",
        sa.Column(
            "referral_registration_processed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column(
        "users", "referral_registration_processed", server_default=sa.false()
    )
    op.create_table(
        "referrals",
        sa.Column(
            "referred_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "referrer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column(
            "qualified_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("referrer_id", "slot", name="uq_referral_slot"),
        sa.CheckConstraint("slot BETWEEN 1 AND 20", name="ck_referral_slot"),
        sa.CheckConstraint(
            "referrer_id != referred_user_id", name="ck_referral_not_self"
        ),
    )
    op.create_index("ix_referrals_referrer_id", "referrals", ["referrer_id"])
    op.create_table(
        "referral_rewards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("milestone", sa.Integer()),
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("star_payments.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallet_transactions.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "milestone", name="uq_referral_milestone"),
        sa.CheckConstraint(
            "(milestone IS NOT NULL AND milestone IN (3,10,20) AND payment_id IS NULL) OR (milestone IS NULL AND payment_id IS NOT NULL)",
            name="ck_referral_reward_source",
        ),
        sa.CheckConstraint("amount > 0", name="ck_referral_reward_positive"),
    )
    op.create_index("ix_referral_rewards_user_id", "referral_rewards", ["user_id"])
    op.create_table(
        "referral_shares",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("prepared_message_id", sa.String(255)),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    # Financial attribution is an audit trail, not disposable schema.
    raise RuntimeError(
        "Referral rewards contain financial history. Use a reviewed forward migration."
    )
