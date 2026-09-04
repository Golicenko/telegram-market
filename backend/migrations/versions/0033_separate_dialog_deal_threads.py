"""Separate permanent dialogs from item-specific deal threads.

Revision ID: 0033_dialog_deal_threads
Revises: 0032_listing_promotion_topup
"""

import uuid

from alembic import op
import sqlalchemy as sa


revision = "0033_dialog_deal_threads"
down_revision = "0032_listing_promotion_topup"
branch_labels = None
depends_on = None


def _copy_thread(bind, source: dict, listing_id, *, deal_id=None, archived_at=None):
    thread_id = uuid.uuid4()
    bind.execute(
        sa.text(
            """INSERT INTO conversations
            (id, listing_id, buyer_id, seller_id, conversation_type, deal_id,
             accepted_price_af_coins, last_message_at, archived_at, created_at, updated_at)
            VALUES (:id, :listing_id, :buyer_id, :seller_id, 'deal', :deal_id,
                    :accepted_price, :last_message_at, :archived_at, :created_at, :updated_at)"""
        ),
        {
            "id": thread_id,
            "listing_id": listing_id,
            "buyer_id": source["buyer_id"],
            "seller_id": source["seller_id"],
            "deal_id": deal_id,
            "accepted_price": source["accepted_price_af_coins"],
            "last_message_at": source["last_message_at"],
            "archived_at": archived_at,
            "created_at": source["created_at"],
            "updated_at": source["updated_at"],
        },
    )
    return thread_id


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("conversation_type", sa.String(length=16), nullable=False, server_default="dialog"),
    )
    op.add_column("conversations", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_index("uq_conversations_participant_pair", table_name="conversations")

    bind = op.get_bind()
    conversations = {
        row["id"]: dict(row)
        for row in bind.execute(sa.text("SELECT * FROM conversations")).mappings()
    }

    # Preserve the permanent dialog row. Each historical deal receives its own
    # thread and only messages explicitly linked to that deal are moved.
    deals = list(
        bind.execute(
            sa.text("SELECT id, listing_id, conversation_id, status, completed_at, cancelled_at FROM deals WHERE conversation_id IS NOT NULL")
        ).mappings()
    )
    for deal in deals:
        source = conversations.get(deal["conversation_id"])
        if not source:
            continue
        bind.execute(sa.text("UPDATE conversations SET deal_id = NULL WHERE id = :id"), {"id": source["id"]})
        archived_at = None
        if deal["status"] in {"completed", "cancelled"}:
            archived_at = deal["completed_at"] or deal["cancelled_at"] or source["updated_at"]
        thread_id = _copy_thread(bind, source, deal["listing_id"], deal_id=deal["id"], archived_at=archived_at)
        bind.execute(sa.text("UPDATE deals SET conversation_id = :new WHERE id = :deal"), {"new": thread_id, "deal": deal["id"]})
        bind.execute(
            sa.text("UPDATE conversation_messages SET conversation_id = :new WHERE conversation_id = :old AND deal_id = :deal"),
            {"new": thread_id, "old": source["id"], "deal": deal["id"]},
        )
        bind.execute(
            sa.text("UPDATE price_offers SET conversation_id = :new WHERE conversation_id = :old AND listing_id = :listing"),
            {"new": thread_id, "old": source["id"], "listing": deal["listing_id"]},
        )
        bind.execute(
            sa.text("""UPDATE conversation_messages m SET conversation_id = :new
                       FROM price_offers o WHERE m.price_offer_id = o.id AND o.conversation_id = :new"""),
            {"new": thread_id},
        )

    # Offers which never became a purchase are also item-specific threads.
    groups = list(
        bind.execute(
            sa.text(
                """SELECT conversation_id, listing_id,
                          bool_or(status IN ('pending','accepted')) AS active
                   FROM price_offers GROUP BY conversation_id, listing_id"""
            )
        ).mappings()
    )
    for group in groups:
        source = conversations.get(group["conversation_id"])
        if not source:
            continue
        archived_at = None if group["active"] else source["updated_at"]
        thread_id = _copy_thread(bind, source, group["listing_id"], archived_at=archived_at)
        bind.execute(
            sa.text("UPDATE price_offers SET conversation_id = :new WHERE conversation_id = :old AND listing_id = :listing"),
            {"new": thread_id, "old": source["id"], "listing": group["listing_id"]},
        )
        bind.execute(
            sa.text("""UPDATE conversation_messages m SET conversation_id = :new
                       FROM price_offers o WHERE m.price_offer_id = o.id AND o.conversation_id = :new"""),
            {"new": thread_id},
        )

    bind.execute(sa.text("UPDATE conversations SET accepted_price_af_coins = NULL, deal_id = NULL WHERE conversation_type = 'dialog'"))
    op.create_check_constraint("ck_conversation_type", "conversations", "conversation_type IN ('dialog','deal')")
    op.create_index("ix_conversations_conversation_type", "conversations", ["conversation_type"])
    op.create_index("ix_conversations_archived_at", "conversations", ["archived_at"])
    op.create_index(
        "uq_conversations_dialog_participant_pair",
        "conversations",
        [sa.text("LEAST(buyer_id, seller_id)"), sa.text("GREATEST(buyer_id, seller_id)")],
        unique=True,
        postgresql_where=sa.text("conversation_type = 'dialog'"),
    )
    op.create_index(
        "uq_conversations_active_negotiation",
        "conversations",
        ["listing_id", "buyer_id", "seller_id"],
        unique=True,
        postgresql_where=sa.text("conversation_type = 'deal' AND deal_id IS NULL AND archived_at IS NULL"),
    )


def downgrade() -> None:
    # Keep every conversation/message row. Recreating the former global unique
    # pair index would require deleting or merging item-specific audit threads.
    op.drop_index("uq_conversations_active_negotiation", table_name="conversations")
    op.drop_index("uq_conversations_dialog_participant_pair", table_name="conversations")
    op.drop_index("ix_conversations_archived_at", table_name="conversations")
    op.drop_index("ix_conversations_conversation_type", table_name="conversations")
    op.drop_constraint("ck_conversation_type", "conversations", type_="check")
    op.drop_column("conversations", "archived_at")
    op.drop_column("conversations", "conversation_type")
