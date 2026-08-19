"""Align listing text and minimum-price validation.

Revision ID: 0015_listing_rules
Revises: 0014_persistent_images
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0015_listing_rules"
down_revision: str | None = "0014_persistent_images"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_listings_brand", table_name="listings")
    op.drop_index("ix_listings_model", table_name="listings")
    op.alter_column("listings", "brand", existing_type=sa.String(length=96), type_=sa.Text(), existing_nullable=False)
    op.alter_column("listings", "model", existing_type=sa.String(length=96), type_=sa.Text(), existing_nullable=False)

    op.drop_constraint("ck_listings_min_price", "listings", type_="check")
    op.create_check_constraint("ck_listings_min_price", "listings", "price_af_coins >= 1")
    op.drop_constraint("ck_conversation_accepted_price", "conversations", type_="check")
    op.create_check_constraint(
        "ck_conversation_accepted_price",
        "conversations",
        "accepted_price_af_coins IS NULL OR accepted_price_af_coins >= 1",
    )
    op.drop_constraint("ck_price_offers_min_price", "price_offers", type_="check")
    op.create_check_constraint("ck_price_offers_min_price", "price_offers", "amount_af_coins >= 1")


def downgrade() -> None:
    op.drop_constraint("ck_price_offers_min_price", "price_offers", type_="check")
    op.create_check_constraint("ck_price_offers_min_price", "price_offers", "amount_af_coins >= 100")
    op.drop_constraint("ck_conversation_accepted_price", "conversations", type_="check")
    op.create_check_constraint(
        "ck_conversation_accepted_price",
        "conversations",
        "accepted_price_af_coins IS NULL OR accepted_price_af_coins >= 100",
    )
    op.drop_constraint("ck_listings_min_price", "listings", type_="check")
    op.create_check_constraint("ck_listings_min_price", "listings", "price_af_coins >= 0")

    op.alter_column("listings", "model", existing_type=sa.Text(), type_=sa.String(length=96), existing_nullable=False)
    op.alter_column("listings", "brand", existing_type=sa.Text(), type_=sa.String(length=96), existing_nullable=False)
    op.create_index("ix_listings_model", "listings", ["model"], unique=False)
    op.create_index("ix_listings_brand", "listings", ["brand"], unique=False)
