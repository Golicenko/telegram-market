"""Durable transfer deadline, independent of chat activity."""
from alembic import op
import sqlalchemy as sa

revision = "0041_seller_delivery_deadline"
down_revision = "0040_listing_game_version"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("deals", sa.Column("seller_delivery_deadline", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_deals_seller_delivery_deadline", "deals", ["seller_delivery_deadline"])
    # Give existing untransferred purchases a full grace period on deployment.
    # Never retroactively refund old purchases immediately during migration.
    op.execute("""
        UPDATE deals SET seller_delivery_deadline = CURRENT_TIMESTAMP + INTERVAL '24 hours'
        WHERE status IN ('paid', 'seller_contacted', 'disputed') AND transfer_started_at IS NULL
    """)


def downgrade():
    raise RuntimeError("Delivery deadlines must be preserved; use a forward migration.")
