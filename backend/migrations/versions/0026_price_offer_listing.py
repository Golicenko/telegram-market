"""Bind every price offer to its exact listing.

Revision ID: 0026_price_offer_listing
Revises: 0025_training_idempotency
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0026_price_offer_listing"
down_revision = "0025_training_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("price_offers", sa.Column("listing_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(
        """
        UPDATE price_offers AS offer
        SET listing_id = conversation.listing_id
        FROM conversations AS conversation
        WHERE offer.conversation_id = conversation.id
          AND offer.listing_id IS NULL
        """
    )
    op.alter_column("price_offers", "listing_id", nullable=False)
    op.create_index("ix_price_offers_listing_id", "price_offers", ["listing_id"])
    op.create_foreign_key(
        "fk_price_offers_listing_id_listings",
        "price_offers",
        "listings",
        ["listing_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_price_offers_listing_id_listings", "price_offers", type_="foreignkey")
    op.drop_index("ix_price_offers_listing_id", table_name="price_offers")
    op.drop_column("price_offers", "listing_id")
