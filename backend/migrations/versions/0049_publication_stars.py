"""Lifetime listing quota, persisted Stars drafts, paginated chat index."""
from alembic import op

revision = "0049_publication_stars"
down_revision = "0048_catalog_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("LOCK TABLE users, listings IN ACCESS EXCLUSIVE MODE")
    op.execute("ALTER TABLE users ADD COLUMN publication_count INTEGER NOT NULL DEFAULT 0")
    # All retained regular listings were created published by the old service.
    # Include sold, hidden, expired and soft-deleted; never guess hard-deleted history.
    op.execute("UPDATE users u SET publication_count = (SELECT count(*) FROM listings l WHERE l.seller_id=u.id AND l.listing_type='regular')")
    op.execute("""CREATE TABLE publication_rules (
        id INTEGER PRIMARY KEY, free_limit INTEGER NOT NULL, price_stars INTEGER NOT NULL, enabled BOOLEAN NOT NULL,
        CONSTRAINT ck_publication_rules CHECK (id=1 AND free_limit>=0 AND price_stars BETWEEN 1 AND 10000))""")
    op.execute("INSERT INTO publication_rules VALUES (1,5,5,true)")
    op.execute("""CREATE TABLE publication_drafts (
        id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        request_id UUID NOT NULL, payload JSONB NOT NULL, price_stars INTEGER NOT NULL,
        invoice_url TEXT, checkout_query_id VARCHAR(255), checkout_at TIMESTAMPTZ,
        payment_id UUID UNIQUE REFERENCES star_payments(id) ON DELETE RESTRICT,
        listing_id UUID UNIQUE REFERENCES listings(id) ON DELETE RESTRICT,
        status VARCHAR(24) NOT NULL, last_error VARCHAR(300), attempts INTEGER NOT NULL DEFAULT 0,
        retry_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_publication_request UNIQUE(user_id,request_id),
        CONSTRAINT ck_publication_price CHECK(price_stars>0),
        CONSTRAINT ck_publication_status CHECK(status IN ('draft','paid','published','review','refund_pending','refunded'))
    )""")
    op.execute("CREATE INDEX ix_publication_drafts_user_id ON publication_drafts(user_id)")
    op.execute("CREATE INDEX ix_publication_drafts_status ON publication_drafts(status)")
    op.execute("CREATE INDEX ix_messages_chat_cursor ON conversation_messages(conversation_id,created_at,id)")


def downgrade():
    # Payment evidence must not be silently dropped on code rollback.
    raise RuntimeError("Preserve publication payments and counters; roll back code with paid publications disabled, not payment data")
