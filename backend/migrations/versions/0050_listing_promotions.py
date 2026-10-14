"""Durable mixed AF/Stars VIP orders; preserve all existing payments."""
from alembic import op

revision = "0050_listing_promotions"
down_revision = "0049_publication_stars"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE listing_promotions (
        id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        request_id UUID NOT NULL, target_key VARCHAR(80) NOT NULL,
        listing_id UUID REFERENCES listings(id) ON DELETE RESTRICT, listing_payload JSONB,
        cost_af NUMERIC(18,2) NOT NULL, balance_af NUMERIC(18,2) NOT NULL, stars INTEGER NOT NULL,
        duration_hours INTEGER NOT NULL, funding JSONB NOT NULL,
        intent_id UUID UNIQUE REFERENCES star_payment_intents(id) ON DELETE RESTRICT,
        payment_id UUID UNIQUE REFERENCES star_payments(id) ON DELETE RESTRICT,
        ledger_id UUID UNIQUE REFERENCES wallet_transactions(id) ON DELETE RESTRICT,
        status VARCHAR(24) NOT NULL, expires_at TIMESTAMPTZ NOT NULL, paid_at TIMESTAMPTZ,
        pinned_until TIMESTAMPTZ, last_error VARCHAR(300),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_promotion_request UNIQUE(user_id,request_id),
        CONSTRAINT ck_promotion_amounts CHECK(cost_af>0 AND balance_af>=0 AND balance_af<=cost_af AND stars>=0 AND duration_hours>0),
        CONSTRAINT ck_promotion_status CHECK(status IN ('awaiting_payment','paid','completed','cancelled','restored'))
    )""")
    op.execute("CREATE INDEX ix_listing_promotions_status ON listing_promotions(status)")
    op.execute("CREATE UNIQUE INDEX uq_promotion_active_target ON listing_promotions(user_id,target_key) WHERE status IN ('awaiting_payment','paid')")
    op.execute("CREATE INDEX ix_training_purchases_created_id ON training_purchases(created_at DESC,id DESC)")


def downgrade():
    raise RuntimeError("Keep VIP payment/hold evidence. Roll back code only after draining paid/pending VIP orders; do not drop financial history.")
