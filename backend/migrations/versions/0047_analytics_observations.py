"""Privacy-bounded UI observations; financial records are not changed/backfilled."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0047_analytics_observations"
down_revision = "0046_seller_order_progress"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("analytics_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("retained_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.execute("INSERT INTO analytics_state (id) VALUES (1)")
    op.create_table("analytics_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_name", sa.String(40), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dedup_key", sa.String(64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True)),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(24)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "dedup_key", name="uq_analytics_event_dedup"))
    op.create_index("ix_analytics_user_time", "analytics_events", ["user_id", "created_at"])
    op.create_index("ix_analytics_name_time", "analytics_events", ["event_name", "created_at"])
    op.create_index("ix_analytics_time", "analytics_events", ["created_at"])


def downgrade():
    raise RuntimeError("Roll back code with analytics disabled; retain collected observations. Data removal requires a reviewed migration.")
