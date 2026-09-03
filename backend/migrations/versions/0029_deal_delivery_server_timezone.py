"""Persist buyer server and Moscow delivery timezone.

Revision ID: 0029_deal_server_timezone
Revises: 0028_content_notifications
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_deal_server_timezone"
down_revision = "0028_content_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("buyer_server", sa.String(length=128), nullable=True))
    op.add_column("deals", sa.Column("delivery_timezone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("deals", "delivery_timezone")
    op.drop_column("deals", "buyer_server")
