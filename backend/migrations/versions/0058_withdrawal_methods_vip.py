"""Persist payout method quotes and historical VIP priority without changing money."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0058_withdrawal_methods_vip"
down_revision = "0057_seller_vip"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("gift_withdrawal_quotes", sa.Column("payout_method", sa.String(64), nullable=False, server_default="manual_gift"))
    op.add_column("withdrawal_requests", sa.Column("vip_priority", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("withdrawal_requests", sa.Column("vip_snapshot", JSONB(), nullable=False, server_default="{}"))
    op.create_index("ix_withdrawal_requests_vip_priority", "withdrawal_requests", ["vip_priority"])


def downgrade():
    # Money-bearing historical snapshots/quotes must not be destructively removed
    # by a code rollback. The prior application ignores these additive columns.
    raise RuntimeError("Roll back application code only: preserve withdrawal quotes and historical VIP snapshots.")
