"""Persist manual gift quotes and immutable payout composition; retain old requests."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0038_manual_gift_withdrawals"
down_revision = "0037_deal_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("gift_withdrawal_quotes",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("budget", sa.Numeric(18, 2), nullable=False),
        sa.Column("gross_af", sa.Numeric(18, 2), nullable=False),
        sa.Column("fee_af", sa.Numeric(18, 2), nullable=False),
        sa.Column("payout_stars", sa.Integer(), nullable=False),
        sa.Column("gift_plan", pg.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("gross_af > 0 AND gross_af <= budget AND payout_stars > 0 AND fee_af = gross_af - payout_stars", name="ck_gift_quote_amounts"))
    op.create_index("ix_gift_withdrawal_quotes_user_id", "gift_withdrawal_quotes", ["user_id"])
    op.add_column("withdrawal_requests", sa.Column("gift_quote_id", pg.UUID(as_uuid=True)))
    op.create_foreign_key("fk_withdrawal_gift_quote", "withdrawal_requests", "gift_withdrawal_quotes", ["gift_quote_id"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_withdrawal_gift_quote", "withdrawal_requests", ["gift_quote_id"])
    op.add_column("withdrawal_requests", sa.Column("fee_af", sa.Numeric(18, 2)))
    op.add_column("withdrawal_requests", sa.Column("payout_stars", sa.Integer()))
    op.add_column("withdrawal_requests", sa.Column("gift_plan", pg.JSONB()))


def downgrade():
    raise RuntimeError("Forward-only: preserve withdrawal quotes and financial history")
