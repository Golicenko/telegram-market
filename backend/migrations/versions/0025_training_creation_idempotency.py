"""Make training product creation safe to retry after a lost response."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0025_training_idempotency"
down_revision = "0024_deal_transfer_reminder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "training_products",
        sa.Column("client_request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_training_product_admin_request",
        "training_products",
        ["admin_id", "client_request_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_training_product_admin_request", "training_products", type_="unique")
    op.drop_column("training_products", "client_request_id")
