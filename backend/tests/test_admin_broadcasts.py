import uuid
from pathlib import Path

import pytest
from fastapi import BackgroundTasks

from app import routes
from app.broadcasts import parse_broadcast_command
from app.config import Settings
from app.models import AdminBroadcast


def test_broadcast_commands_are_explicit_and_support_slash_or_hash():
    assert parse_broadcast_command("#рассылка Важное сообщение") == "Важное сообщение"
    assert parse_broadcast_command("/рассылка Важное сообщение") == "Важное сообщение"
    assert parse_broadcast_command("  /РАССЫЛКА   Текст  ") == "Текст"
    assert parse_broadcast_command("#рассылка") == ""
    assert parse_broadcast_command("#рассылкаспам") is None
    assert parse_broadcast_command("обычное сообщение") is None


def test_broadcast_update_id_and_active_job_are_unique_in_database_model():
    constraint = next(
        item for item in AdminBroadcast.__table__.constraints
        if item.name == "uq_admin_broadcast_telegram_update"
    )
    assert [column.name for column in constraint.columns] == ["telegram_update_id"]
    active_index = next(
        item for item in AdminBroadcast.__table__.indexes
        if item.name == "uq_admin_broadcast_active_admin"
    )
    assert active_index.unique is True
    assert active_index.dialect_options["postgresql"]["where"] is not None


@pytest.mark.asyncio
async def test_retried_telegram_update_queues_broadcast_only_once(monkeypatch):
    broadcast_id = uuid.uuid4()
    claims = iter([broadcast_id, None])

    async def fake_create(*_args, **_kwargs):
        return next(claims)

    async def fake_run(_broadcast_id):
        return None

    monkeypatch.setattr(routes, "create_admin_broadcast", fake_create)
    monkeypatch.setattr(routes, "run_admin_broadcast", fake_run)
    update = {
        "update_id": 987654,
        "message": {
            "message_id": 1,
            "from": {"id": 42, "first_name": "Admin"},
            "text": "#рассылка Только один раз",
        },
    }
    settings = Settings(bot_token="test-token", admin_id=42)
    first_tasks = BackgroundTasks()
    second_tasks = BackgroundTasks()

    secret = settings.effective_telegram_webhook_secret
    first = await routes.telegram_webhook(update, first_tasks, secret, object(), settings)
    second = await routes.telegram_webhook(update, second_tasks, secret, object(), settings)

    assert first == {"ok": True, "accepted": True}
    assert second == {"ok": True, "accepted": False}
    assert len(first_tasks.tasks) == 1
    assert len(second_tasks.tasks) == 0


def test_webhook_secret_is_derived_without_exposing_bot_token():
    settings = Settings(bot_token="123456:PRIVATE")
    assert len(settings.effective_telegram_webhook_secret) == 64
    assert "PRIVATE" not in settings.effective_telegram_webhook_secret


def test_broadcast_migration_is_additive_and_worker_has_status_guard():
    backend = Path(__file__).parents[1]
    migration = (backend / "migrations" / "versions" / "0013_idempotent_admin_broadcasts.py").read_text(encoding="utf-8")
    upgrade = migration.split("def downgrade", 1)[0]
    worker = (backend / "app" / "broadcasts.py").read_text(encoding="utf-8")
    assert "telegram_update_id" in migration
    assert "uq_admin_broadcast_active_admin" in migration
    assert "drop_table" not in upgrade
    assert 'broadcast.status != "pending"' in worker
    assert ".on_conflict_do_nothing()" in worker
