"""Account subtype and encrypted grants, without converting legacy account rows."""

from alembic import op
import sqlalchemy as sa

revision = "0055_account_autodelivery"
down_revision = "0054_private_chat_photos"
branch_labels = None
depends_on = None


def upgrade():
    statements = [
        "ALTER TABLE uploaded_images ADD COLUMN support_private BOOLEAN NOT NULL DEFAULT false",
        "UPDATE uploaded_images AS i SET support_private=true WHERE EXISTS(SELECT 1 FROM support_tickets s WHERE s.screenshot_url='/api/media/'||i.id::text) AND NOT EXISTS(SELECT 1 FROM listing_images l WHERE l.url='/api/media/'||i.id::text) AND NOT EXISTS(SELECT 1 FROM training_products t WHERE t.cover_url='/api/media/'||i.id::text)",
        "CREATE TABLE account_videos (id UUID PRIMARY KEY, owner_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT, object_key TEXT NOT NULL UNIQUE, content_type VARCHAR(64) NOT NULL, size_bytes BIGINT, ready BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
        "CREATE INDEX ix_account_videos_owner_id ON account_videos(owner_id)",
        "ALTER TABLE listings ADD COLUMN product_kind VARCHAR(16) NOT NULL DEFAULT 'car'",
        "ALTER TABLE listings ADD COLUMN video_asset_id UUID REFERENCES account_videos(id) ON DELETE RESTRICT",
        "CREATE INDEX ix_listings_product_kind ON listings(product_kind)",
        "ALTER TABLE listings DROP CONSTRAINT ck_listings_positive_stats",
        "ALTER TABLE listings ALTER COLUMN power_hp DROP NOT NULL",
        "ALTER TABLE listings ALTER COLUMN max_speed_kph DROP NOT NULL",
        "ALTER TABLE listings ADD CONSTRAINT ck_listings_product_kind CHECK(product_kind IN ('car','account'))",
        "ALTER TABLE listings ADD CONSTRAINT ck_listings_positive_stats CHECK((product_kind='car' AND power_hp IS NOT NULL AND max_speed_kph IS NOT NULL AND power_hp>0 AND max_speed_kph>0) OR (product_kind='account' AND listing_type='regular' AND power_hp IS NULL AND max_speed_kph IS NULL))",
        "ALTER TABLE deals ADD COLUMN product_kind VARCHAR(16) NOT NULL DEFAULT 'car'",
        "CREATE TABLE account_secrets (listing_id UUID PRIMARY KEY REFERENCES listings(id) ON DELETE RESTRICT, key_id VARCHAR(64) NOT NULL, ciphertext BYTEA, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())",
        "CREATE TABLE account_grants (deal_id UUID PRIMARY KEY REFERENCES deals(id) ON DELETE RESTRICT, key_id VARCHAR(64) NOT NULL, ciphertext BYTEA, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), first_opened_at TIMESTAMPTZ, last_opened_at TIMESTAMPTZ, open_count INTEGER NOT NULL DEFAULT 0, deleted_at TIMESTAMPTZ)",
        "ALTER TABLE conversation_messages ADD COLUMN account_card_id UUID REFERENCES account_grants(deal_id) ON DELETE RESTRICT",
        "CREATE TABLE account_pins (id UUID PRIMARY KEY, listing_id UUID NOT NULL REFERENCES listings(id) ON DELETE RESTRICT, user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT, request_id UUID NOT NULL, invoice_url TEXT, checkout_query_id VARCHAR(255), checkout_at TIMESTAMPTZ, payment_id UUID UNIQUE REFERENCES star_payments(id) ON DELETE RESTRICT, status VARCHAR(24) NOT NULL DEFAULT 'pending', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), CONSTRAINT uq_account_pin_request UNIQUE(user_id,request_id))",
    ]
    for statement in statements:
        op.execute(sa.text(statement))


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM account_videos) OR EXISTS(SELECT 1 FROM listings WHERE product_kind='account')"
        )
    ):
        raise RuntimeError(
            "Account data exists: roll back application, preserve additive schema and secrets"
        )
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM uploaded_images WHERE support_private)")
    ):
        raise RuntimeError("Private support images exist: preserve privacy schema")
    op.drop_column("uploaded_images", "support_private")
    op.drop_column("conversation_messages", "account_card_id")
    for table in ("account_pins", "account_grants", "account_secrets"):
        op.drop_table(table)
    op.drop_column("deals", "product_kind")
    op.drop_constraint("ck_listings_positive_stats", "listings")
    op.drop_constraint("ck_listings_product_kind", "listings")
    op.execute("ALTER TABLE listings ALTER COLUMN power_hp SET NOT NULL")
    op.execute("ALTER TABLE listings ALTER COLUMN max_speed_kph SET NOT NULL")
    op.execute(
        "ALTER TABLE listings ADD CONSTRAINT ck_listings_positive_stats CHECK(power_hp>0 AND max_speed_kph>0)"
    )
    op.drop_index("ix_listings_product_kind", table_name="listings")
    op.drop_column("listings", "video_asset_id")
    op.drop_column("listings", "product_kind")
    op.drop_table("account_videos")
