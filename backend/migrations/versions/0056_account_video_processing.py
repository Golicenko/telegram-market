"""Add restart-safe processing metadata; leave existing ready videos untouched."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0056_account_video_processing"
down_revision = "0055_account_autodelivery"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "account_videos", sa.Column("processing_status", sa.String(24), nullable=True)
    )
    op.add_column(
        "account_videos", sa.Column("processing_meta", JSONB(), nullable=True)
    )
    op.add_column(
        "account_videos", sa.Column("processed_key", sa.Text(), nullable=True)
    )
    op.create_index(
        "ix_account_videos_processing_status", "account_videos", ["processing_status"]
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM account_videos WHERE processed_key IS NOT NULL LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError(
            "Keep the additive schema: prepared videos still reference processed_key. Migrate media before downgrade."
        )
    op.drop_index("ix_account_videos_processing_status", "account_videos")
    op.drop_column("account_videos", "processed_key")
    op.drop_column("account_videos", "processing_meta")
    op.drop_column("account_videos", "processing_status")
