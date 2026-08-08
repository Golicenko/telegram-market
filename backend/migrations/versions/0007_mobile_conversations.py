"""Make conversations permanent per user pair and add mobile chat state."""

from alembic import op
import sqlalchemy as sa


revision = "0007_mobile_conversations"
down_revision = "0006_split_wallet_balances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("buyer_hidden_at", sa.DateTime(timezone=True)))
    op.add_column("conversations", sa.Column("seller_hidden_at", sa.DateTime(timezone=True)))
    op.add_column("conversation_messages", sa.Column("client_message_id", sa.Uuid()))
    op.create_unique_constraint(
        "uq_conversation_message_client_id",
        "conversation_messages",
        ["conversation_id", "sender_id", "client_message_id"],
    )
    # The legacy uniqueness can block the temporary context move while duplicate
    # conversations still coexist. Remove it before merging; the migration is
    # transactional, so a failure restores the original constraint and data.
    op.drop_constraint("uq_conversation_listing_buyer", "conversations", type_="unique")

    # Preserve all history. Existing duplicates are merged into the oldest
    # conversation for each unordered participant pair before uniqueness is added.
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   FIRST_VALUE(id) OVER (
                       PARTITION BY LEAST(buyer_id, seller_id), GREATEST(buyer_id, seller_id)
                       ORDER BY created_at, id
                   ) AS keep_id
            FROM conversations
        )
        UPDATE conversation_messages m
        SET conversation_id = r.keep_id
        FROM ranked r
        WHERE m.conversation_id = r.id AND r.id <> r.keep_id
    """)
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   FIRST_VALUE(id) OVER (
                       PARTITION BY LEAST(buyer_id, seller_id), GREATEST(buyer_id, seller_id)
                       ORDER BY created_at, id
                   ) AS keep_id
            FROM conversations
        )
        UPDATE price_offers p
        SET conversation_id = r.keep_id
        FROM ranked r
        WHERE p.conversation_id = r.id AND r.id <> r.keep_id
    """)
    op.execute("""
        CREATE TEMP TABLE conversation_merge_context ON COMMIT DROP AS
        SELECT DISTINCT ON (LEAST(buyer_id, seller_id), GREATEST(buyer_id, seller_id))
               FIRST_VALUE(id) OVER (
                   PARTITION BY LEAST(buyer_id, seller_id), GREATEST(buyer_id, seller_id)
                   ORDER BY created_at, id
               ) AS keep_id,
               listing_id, deal_id, accepted_price_af_coins, last_message_at
        FROM conversations
        ORDER BY LEAST(buyer_id, seller_id), GREATEST(buyer_id, seller_id),
                 (deal_id IS NOT NULL) DESC, last_message_at DESC NULLS LAST, created_at DESC
    """)
    op.execute("""
        UPDATE conversations c SET deal_id = NULL
        FROM conversation_merge_context m
        WHERE c.deal_id = m.deal_id AND c.id <> m.keep_id
    """)
    op.execute("""
        UPDATE conversations c
        SET listing_id = m.listing_id,
            deal_id = m.deal_id,
            accepted_price_af_coins = m.accepted_price_af_coins,
            last_message_at = GREATEST(c.last_message_at, m.last_message_at)
        FROM conversation_merge_context m
        WHERE c.id = m.keep_id
    """)
    op.execute("""
        DELETE FROM conversations c
        USING conversations older
        WHERE LEAST(c.buyer_id, c.seller_id) = LEAST(older.buyer_id, older.seller_id)
          AND GREATEST(c.buyer_id, c.seller_id) = GREATEST(older.buyer_id, older.seller_id)
          AND (c.created_at, c.id) > (older.created_at, older.id)
    """)
    op.create_index(
        "uq_conversations_participant_pair",
        "conversations",
        [sa.text("LEAST(buyer_id, seller_id)"), sa.text("GREATEST(buyer_id, seller_id)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_conversations_participant_pair", table_name="conversations")
    op.create_unique_constraint("uq_conversation_listing_buyer", "conversations", ["listing_id", "buyer_id"])
    op.drop_constraint("uq_conversation_message_client_id", "conversation_messages", type_="unique")
    op.drop_column("conversation_messages", "client_message_id")
    op.drop_column("conversations", "seller_hidden_at")
    op.drop_column("conversations", "buyer_hidden_at")
