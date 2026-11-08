"""Add private normalized chat images; old messages and balances stay intact."""
from alembic import op
import sqlalchemy as sa

revision = "0054_private_chat_photos"
down_revision = "0053_feedback_collection"
branch_labels = None
depends_on = None


def upgrade():
    for statement in (
        """CREATE TABLE private_chat_images (
        id UUID PRIMARY KEY, conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        owner_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        data BYTEA NOT NULL, preview BYTEA NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_private_chat_image_dimensions CHECK(width > 0 AND height > 0))""",
        "ALTER TABLE conversation_messages ADD COLUMN media_id UUID UNIQUE REFERENCES private_chat_images(id) ON DELETE RESTRICT",
        "ALTER TABLE conversation_messages ADD COLUMN media_width INTEGER",
        "ALTER TABLE conversation_messages ADD COLUMN media_height INTEGER",
        "ALTER TABLE conversation_messages DROP CONSTRAINT ck_conversation_message_type",
        "ALTER TABLE conversation_messages ADD CONSTRAINT ck_conversation_message_type CHECK(message_type IN ('text','system','offer','photo'))",
        """ALTER TABLE conversation_messages ADD CONSTRAINT ck_message_photo CHECK (
          (message_type = 'photo' AND media_id IS NOT NULL AND media_width IS NOT NULL AND media_height IS NOT NULL AND media_width > 0 AND media_height > 0)
          OR (message_type != 'photo' AND media_id IS NULL))""",
        "CREATE INDEX ix_messages_photo_rate ON conversation_messages(conversation_id,sender_id,created_at) WHERE message_type = 'photo'",
    ):
        op.execute(sa.text(statement))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM private_chat_images)")).scalar():
        raise RuntimeError("Private chat photos exist: rollback application without dropping preserved media")
    op.drop_index("ix_messages_photo_rate", table_name="conversation_messages")
    op.drop_constraint("ck_message_photo", "conversation_messages")
    op.drop_constraint("ck_conversation_message_type", "conversation_messages")
    op.execute("ALTER TABLE conversation_messages ADD CONSTRAINT ck_conversation_message_type CHECK(message_type IN ('text','system','offer'))")
    op.drop_column("conversation_messages", "media_id")
    op.drop_column("conversation_messages", "media_width")
    op.drop_column("conversation_messages", "media_height")
    op.drop_table("private_chat_images")
