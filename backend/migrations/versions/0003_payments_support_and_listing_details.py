"""Add real Stars intents, support tickets and complete listing details."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_payments_support"
down_revision = "0002_market_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)

    op.add_column("listings", sa.Column("description", sa.Text(), nullable=False, server_default=""))
    op.add_column("listings", sa.Column("views_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("ck_listings_views_nonnegative", "listings", "views_count >= 0")

    op.add_column("account_listings", sa.Column("level", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("account_listings", sa.Column("game_assets", sa.Text()))
    op.add_column("account_listings", sa.Column("auto_delivery", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_check_constraint("ck_account_listings_level", "account_listings", "level >= 0")

    op.create_table(
        "star_payment_intents",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("invoice_payload", sa.String(128), nullable=False, unique=True),
        sa.Column("invoice_link", sa.Text()),
        sa.Column("xtr_amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("xtr_amount BETWEEN 100 AND 1000", name="ck_star_payment_intent_amount"),
        sa.CheckConstraint("status IN ('pending','paid','cancelled','expired')", name="ck_star_payment_intent_status"),
    )
    op.create_index("ix_star_payment_intents_user_id", "star_payment_intents", ["user_id"])
    op.create_index("ix_star_payment_intents_status", "star_payment_intents", ["status"])

    op.create_table(
        "support_tickets",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("screenshot_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('open','in_progress','resolved','closed')", name="ck_support_ticket_status"),
    )
    op.create_index("ix_support_tickets_user_id", "support_tickets", ["user_id"])
    op.create_index("ix_support_tickets_status", "support_tickets", ["status"])

    op.create_table(
        "support_messages",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("ticket_id", uuid_type, sa.ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_support_messages_ticket_id", "support_messages", ["ticket_id"])
    op.create_index("ix_support_messages_created_at", "support_messages", ["created_at"])

    op.create_table(
        "advertisements",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("link_url", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("admin_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_advertisements_is_active", "advertisements", ["is_active"])


def downgrade() -> None:
    op.drop_table("advertisements")
    op.drop_table("support_messages")
    op.drop_table("support_tickets")
    op.drop_table("star_payment_intents")
    op.drop_constraint("ck_account_listings_level", "account_listings", type_="check")
    op.drop_column("account_listings", "auto_delivery")
    op.drop_column("account_listings", "game_assets")
    op.drop_column("account_listings", "level")
    op.drop_constraint("ck_listings_views_nonnegative", "listings", type_="check")
    op.drop_column("listings", "views_count")
    op.drop_column("listings", "description")
