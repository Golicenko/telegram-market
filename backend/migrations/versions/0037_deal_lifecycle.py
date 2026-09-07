"""Durable reminder rounds, escalation and append-only deal timeline."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0037_deal_lifecycle"
down_revision = "0036_inactivity_state"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("deals", sa.Column("buyer_reminder_round", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("deals", sa.Column("needs_admin_review_at", sa.DateTime(timezone=True)))
    op.create_index("ix_deals_needs_admin_review_at", "deals", ["needs_admin_review_at"])
    op.create_table("deal_events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("deal_id", pg.UUID(as_uuid=True), sa.ForeignKey("deals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("from_status", sa.String(32)), sa.Column("to_status", sa.String(32)),
        sa.Column("request_id", pg.UUID(as_uuid=True)),
        sa.Column("details", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("deal_id", "request_id", name="uq_deal_event_request"))
    op.create_index("ix_deal_events_deal_id", "deal_events", ["deal_id"])


def downgrade():
    raise RuntimeError("Forward-only: preserve deal audit history; use a reviewed forward migration")
