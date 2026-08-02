from alembic import op
import sqlalchemy as sa

revision = "0005_message_read_status"
down_revision = "0004_remove_min_price"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversation_messages",
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.add_column(
        "conversation_messages",
        sa.Column(
            "read_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_conversation_messages_is_read",
        "conversation_messages",
        ["is_read"],
    )


def downgrade():
    op.drop_index(
        "ix_conversation_messages_is_read",
        table_name="conversation_messages",
    )

    op.drop_column("conversation_messages", "read_at")
    op.drop_column("conversation_messages", "is_read")
  
