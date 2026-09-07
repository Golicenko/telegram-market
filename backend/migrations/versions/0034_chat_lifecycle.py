"""Support terminal offers and archive legacy empty/final chat threads."""
from alembic import op

revision = "0034_chat_lifecycle"
down_revision = "0033_dialog_deal_threads"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_price_offers_status", "price_offers", type_="check")
    op.create_check_constraint("ck_price_offers_status", "price_offers",
        "status IN ('pending','accepted','rejected','countered','expired','cancelled')")
    op.execute("""
        UPDATE conversations c SET archived_at = now()
        WHERE c.conversation_type = 'deal' AND c.archived_at IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM deals d WHERE d.id = c.deal_id AND d.conversation_id = c.id
            AND d.buyer_id = c.buyer_id AND d.seller_id = c.seller_id
            AND d.status IN ('paid','seller_contacted','transfer_in_progress','buyer_confirmed','disputed')
        )
        AND NOT (c.deal_id IS NULL AND EXISTS (
            SELECT 1 FROM price_offers p JOIN listings l ON l.id = p.listing_id
            WHERE p.conversation_id = c.id AND p.status IN ('pending','accepted')
            AND p.listing_id = c.listing_id
            AND l.status = 'active' AND l.deleted_at IS NULL
        ))
    """)


def downgrade():
    # Preserve history and terminal meaning on rollback to the old constraint.
    op.execute("UPDATE price_offers SET status = 'rejected' WHERE status IN ('expired','cancelled')")
    op.drop_constraint("ck_price_offers_status", "price_offers", type_="check")
    op.create_check_constraint("ck_price_offers_status", "price_offers",
        "status IN ('pending','accepted','rejected','countered')")
