"""Record manual gift fulfilment without fabricating historical deliveries."""
from alembic import op

revision = "0052_gift_delivery_progress"
down_revision = "0051_vip_expiries"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE withdrawal_requests ADD COLUMN gift_deliveries JSONB NOT NULL DEFAULT '[]'::jsonb")


def downgrade():
    raise RuntimeError("Do not discard partial payout evidence. Resolve partial gifts before rolling back application code.")
