"""Link deals to permanent conversations and store delivery estimates."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_deal_chat_delivery"
down_revision = "0011_training_star_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "listings",
        sa.Column("delivery_time_estimate", sa.String(24), nullable=False, server_default="up_to_1h"),
    )
    op.create_check_constraint(
        "ck_listings_delivery_time",
        "listings",
        "delivery_time_estimate IN ('up_to_15m','up_to_30m','up_to_1h','up_to_3h','up_to_6h','up_to_12h','up_to_24h')",
    )

    op.add_column(
        "deals",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_deals_conversation",
        "deals",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_deals_conversation_id", "deals", ["conversation_id"])
    op.execute(
        """
        UPDATE deals AS deal
        SET conversation_id = conversation.id
        FROM conversations AS conversation
        WHERE conversation.deal_id = deal.id
          AND deal.conversation_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_deals_conversation_id", table_name="deals")
    op.drop_constraint("fk_deals_conversation", "deals", type_="foreignkey")
    op.drop_column("deals", "conversation_id")
    op.drop_constraint("ck_listings_delivery_time", "listings", type_="check")
    op.drop_column("listings", "delivery_time_estimate")
