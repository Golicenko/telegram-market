"""Add unique listing views and public likes."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0022_listing_engagement"
down_revision = "0021_reliable_broadcasts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "listing_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_id", "user_id", name="uq_listing_view_listing_user"),
    )
    op.create_index("ix_listing_views_listing_id", "listing_views", ["listing_id"])
    op.create_index("ix_listing_views_user_id", "listing_views", ["user_id"])
    op.create_index("ix_listing_views_viewed_at", "listing_views", ["viewed_at"])
    op.create_table(
        "listing_likes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_id", "user_id", name="uq_listing_like_listing_user"),
    )
    op.create_index("ix_listing_likes_listing_id", "listing_likes", ["listing_id"])
    op.create_index("ix_listing_likes_user_id", "listing_likes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_listing_likes_user_id", table_name="listing_likes")
    op.drop_index("ix_listing_likes_listing_id", table_name="listing_likes")
    op.drop_table("listing_likes")
    op.drop_index("ix_listing_views_viewed_at", table_name="listing_views")
    op.drop_index("ix_listing_views_user_id", table_name="listing_views")
    op.drop_index("ix_listing_views_listing_id", table_name="listing_views")
    op.drop_table("listing_views")
