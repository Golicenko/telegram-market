"""Persist administrative balance command identities; preserve historical entries."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0044_admin_balance_idempotency"
down_revision = "0043_referral_bonus_safety"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("admin_balance_adjustments", sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_unique_constraint("uq_admin_balance_request", "admin_balance_adjustments", ["admin_id", "request_id"])


def downgrade():
    # Keep this additive column during operational rollback: dropping it loses
    # command identities, although neither balances nor ledger entries change.
    op.drop_constraint("uq_admin_balance_request", "admin_balance_adjustments", type_="unique")
    op.drop_column("admin_balance_adjustments", "request_id")
