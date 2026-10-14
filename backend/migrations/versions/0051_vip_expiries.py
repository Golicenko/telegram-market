"""Expiry invitations do not modify existing pin durations or listing status."""
from alembic import op

revision = "0051_vip_expiries"
down_revision = "0050_listing_promotions"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE vip_expiries (
        id UUID PRIMARY KEY,
        listing_id UUID NOT NULL REFERENCES listings(id) ON DELETE RESTRICT,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        pinned_until TIMESTAMPTZ NOT NULL,
        price_stars INTEGER NOT NULL, duration_hours INTEGER NOT NULL,
        redeemed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_vip_expiry_period UNIQUE(listing_id,pinned_until),
        CONSTRAINT ck_vip_expiry_tariff CHECK(price_stars>0 AND duration_hours>0)
    )""")
    op.execute("ALTER TABLE listing_promotions ADD COLUMN renewal_id UUID REFERENCES vip_expiries(id) ON DELETE RESTRICT")
    op.execute("CREATE INDEX ix_listings_vip_expiry ON listings(pinned_until,id) WHERE pinned_until IS NOT NULL AND status='active' AND deleted_at IS NULL")


def downgrade():
    raise RuntimeError("Retain renewal/payment evidence. Drain pending VIP payments before rolling back application code; do not drop history.")
