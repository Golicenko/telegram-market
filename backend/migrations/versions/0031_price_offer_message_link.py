"""Link structured chat cards to their exact price offer.

Revision ID: 0031_price_offer_message_link
Revises: 0030_seller_response_timeout
"""

from alembic import op
import sqlalchemy as sa


revision = "0031_price_offer_message_link"
down_revision = "0030_seller_response_timeout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation_messages", sa.Column("price_offer_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_conversation_messages_price_offer_id_price_offers",
        "conversation_messages",
        "price_offers",
        ["price_offer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_conversation_messages_price_offer_id",
        "conversation_messages",
        ["price_offer_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_messages_price_offer_id", table_name="conversation_messages")
    op.drop_constraint(
        "fk_conversation_messages_price_offer_id_price_offers",
        "conversation_messages",
        type_="foreignkey",
    )
    op.drop_column("conversation_messages", "price_offer_id")
