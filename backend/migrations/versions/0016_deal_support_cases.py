"""Link support cases to deals and add an immutable case audit trail.

Revision ID: 0016_deal_support
Revises: 0015_listing_rules
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0016_deal_support"
down_revision: str | None = "0015_listing_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.add_column("support_tickets", sa.Column("author_id", uuid_type, nullable=True))
    op.add_column("support_tickets", sa.Column("case_type", sa.String(16), nullable=False, server_default="general"))
    op.add_column("support_tickets", sa.Column("deal_id", uuid_type, nullable=True))
    op.add_column("support_tickets", sa.Column("listing_id", uuid_type, nullable=True))
    op.add_column("support_tickets", sa.Column("buyer_id", uuid_type, nullable=True))
    op.add_column("support_tickets", sa.Column("seller_id", uuid_type, nullable=True))
    op.add_column("support_tickets", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("support_tickets", sa.Column("unread_by_admin", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute("UPDATE support_tickets SET author_id = user_id")
    op.alter_column("support_tickets", "author_id", nullable=False)
    for column in ("author_id", "deal_id", "listing_id", "buyer_id", "seller_id"):
        target = "deals" if column == "deal_id" else "listings" if column == "listing_id" else "users"
        op.create_foreign_key(f"fk_support_tickets_{column}", "support_tickets", target, [column], ["id"], ondelete="RESTRICT")
        op.create_index(f"ix_support_tickets_{column}", "support_tickets", [column])
    op.create_index("ix_support_tickets_case_type", "support_tickets", ["case_type"])
    op.create_index("ix_support_tickets_unread_by_admin", "support_tickets", ["unread_by_admin"])
    op.create_check_constraint("ck_support_ticket_case_type", "support_tickets", "case_type IN ('general','deal')")
    op.create_check_constraint(
        "ck_support_ticket_deal_context",
        "support_tickets",
        "case_type = 'general' OR (deal_id IS NOT NULL AND listing_id IS NOT NULL AND buyer_id IS NOT NULL AND seller_id IS NOT NULL)",
    )
    op.create_index(
        "uq_support_active_deal",
        "support_tickets",
        ["deal_id"],
        unique=True,
        postgresql_where=sa.text("case_type = 'deal' AND status IN ('open','in_progress')"),
    )
    op.add_column("support_messages", sa.Column("client_request_id", uuid_type, nullable=True))
    op.create_unique_constraint(
        "uq_support_message_client_request",
        "support_messages",
        ["ticket_id", "sender_id", "client_request_id"],
    )

    op.create_table(
        "support_case_events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("ticket_id", uuid_type, sa.ForeignKey("support_tickets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", uuid_type, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("from_status", sa.String(24), nullable=True),
        sa.Column("to_status", sa.String(24), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_support_case_events_ticket_id", "support_case_events", ["ticket_id"])
    op.create_index("ix_support_case_events_actor_id", "support_case_events", ["actor_id"])
    op.create_index("ix_support_case_events_created_at", "support_case_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("support_case_events")
    op.drop_constraint("uq_support_message_client_request", "support_messages", type_="unique")
    op.drop_column("support_messages", "client_request_id")
    op.drop_index("uq_support_active_deal", table_name="support_tickets")
    op.drop_constraint("ck_support_ticket_deal_context", "support_tickets", type_="check")
    op.drop_constraint("ck_support_ticket_case_type", "support_tickets", type_="check")
    op.drop_index("ix_support_tickets_unread_by_admin", table_name="support_tickets")
    op.drop_index("ix_support_tickets_case_type", table_name="support_tickets")
    for column in ("seller_id", "buyer_id", "listing_id", "deal_id", "author_id"):
        op.drop_index(f"ix_support_tickets_{column}", table_name="support_tickets")
        op.drop_constraint(f"fk_support_tickets_{column}", "support_tickets", type_="foreignkey")
    for column in ("unread_by_admin", "resolved_at", "seller_id", "buyer_id", "listing_id", "deal_id", "case_type", "author_id"):
        op.drop_column("support_tickets", column)
