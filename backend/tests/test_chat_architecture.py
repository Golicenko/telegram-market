import uuid

import pytest
from pydantic import ValidationError

from app.models import Conversation, ConversationMessage
from app.schemas import ConversationMessageCreate


def test_one_conversation_index_is_unique_per_participant_pair():
    index = next(item for item in Conversation.__table__.indexes if item.name == "uq_conversations_participant_pair")
    assert index.unique is True
    expressions = " ".join(str(item) for item in index.expressions)
    assert "LEAST" in expressions and "GREATEST" in expressions


def test_message_idempotency_is_enforced_by_database():
    constraint = next(
        item for item in ConversationMessage.__table__.constraints
        if item.name == "uq_conversation_message_client_id"
    )
    assert [column.name for column in constraint.columns] == [
        "conversation_id", "sender_id", "client_message_id"
    ]


def test_client_message_id_is_required_and_long_messages_are_supported():
    message_id = uuid.uuid4()
    assert ConversationMessageCreate(body="x" * 4000, client_message_id=message_id).client_message_id == message_id
    with pytest.raises(ValidationError):
        ConversationMessageCreate(body="test")
    with pytest.raises(ValidationError):
        ConversationMessageCreate(body="x" * 4001, client_message_id=message_id)


def test_read_receipt_fields_are_server_backed():
    assert "is_read" in ConversationMessage.__table__.columns
    assert "read_at" in ConversationMessage.__table__.columns


def test_mobile_migration_drops_legacy_uniqueness_before_context_merge():
    from pathlib import Path

    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0007_mobile_conversations.py"
    source = migration.read_text(encoding="utf-8")
    drop_position = source.index('op.drop_constraint("uq_conversation_listing_buyer"')
    context_move_position = source.index("UPDATE conversations c\n        SET listing_id")
    assert drop_position < context_move_position
