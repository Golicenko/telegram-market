"""Add per-user content badges and training views.

Revision ID: 0028_content_notifications
Revises: 0027_training_large_video
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0028_content_notifications"
down_revision = "0027_training_large_video"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE content_publication_revision_seq START WITH 1")
    op.add_column("listings", sa.Column("content_revision", sa.BigInteger(), nullable=True))
    op.add_column("training_products", sa.Column("views_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("training_products", sa.Column("content_revision", sa.BigInteger(), nullable=True))
    op.add_column("training_products", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_training_products_views_nonnegative", "training_products", "views_count >= 0")
    op.create_index("ix_listings_content_revision", "listings", ["content_revision"])
    op.create_index("ix_training_products_content_revision", "training_products", ["content_revision"])
    op.create_index("ix_training_products_published_at", "training_products", ["published_at"])

    # Existing public content receives deterministic revisions, while drafts remain invisible.
    op.execute("""
        UPDATE listings
        SET content_revision = nextval('content_publication_revision_seq')
        WHERE listing_type = 'unique' AND status IN ('active', 'reserved') AND deleted_at IS NULL
    """)
    op.execute("""
        UPDATE training_products
        SET content_revision = nextval('content_publication_revision_seq'),
            published_at = COALESCE(updated_at, created_at, now())
        WHERE published IS TRUE AND deleted_at IS NULL
    """)

    op.create_table(
        "content_seen_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section", sa.String(length=24), nullable=False),
        sa.Column("last_seen_revision", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("section IN ('training','unique')", name="ck_content_seen_section"),
        sa.CheckConstraint("last_seen_revision >= 0", name="ck_content_seen_revision"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "section", name="uq_content_seen_user_section"),
    )
    op.create_index("ix_content_seen_states_user_id", "content_seen_states", ["user_id"])

    op.create_table(
        "training_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["training_products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "user_id", name="uq_training_view_product_user"),
    )
    op.create_index("ix_training_views_product_id", "training_views", ["product_id"])
    op.create_index("ix_training_views_user_id", "training_views", ["user_id"])
    op.create_index("ix_training_views_viewed_at", "training_views", ["viewed_at"])


def downgrade() -> None:
    op.drop_table("training_views")
    op.drop_table("content_seen_states")
    op.drop_index("ix_training_products_published_at", table_name="training_products")
    op.drop_index("ix_training_products_content_revision", table_name="training_products")
    op.drop_index("ix_listings_content_revision", table_name="listings")
    op.drop_constraint("ck_training_products_views_nonnegative", "training_products", type_="check")
    op.drop_column("training_products", "published_at")
    op.drop_column("training_products", "content_revision")
    op.drop_column("training_products", "views_count")
    op.drop_column("listings", "content_revision")
    op.execute("DROP SEQUENCE content_publication_revision_seq")
