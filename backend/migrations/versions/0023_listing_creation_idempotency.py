"""Make listing creation safe to retry after a lost response."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0023_listing_idempotency"
down_revision = "0022_listing_engagement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "listings",
        sa.Column("client_request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_listing_seller_client_request",
        "listings",
        ["seller_id", "client_request_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_listing_seller_client_request", "listings", type_="unique")
    op.drop_column("listings", "client_request_id")
