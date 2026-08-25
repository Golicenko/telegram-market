import uuid
from pathlib import Path

import pytest
from fastapi import BackgroundTasks

from app import routes
from app.bot import BroadcastSendResult, broadcast_market_payload
from app.broadcasts import parse_broadcast_command, send_with_bounded_rate_limit
from app.config import Settings
from app.models import AdminBroadcast, AdminBroadcastRecipient


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
    active_where = str(active_index.dialect_options["postgresql"]["where"])
    assert "queued" in active_where and "running" in active_where
    assert "completed" not in active_where


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
    assert len(first_tasks.tasks) == 2
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
    assert 'broadcast.status not in {"queued", "running"}' in worker
    assert ".on_conflict_do_nothing()" in worker


def test_recipient_delivery_is_unique_per_broadcast_and_user():
    constraint = next(
        item for item in AdminBroadcastRecipient.__table__.constraints
        if item.name == "uq_broadcast_recipient_user"
    )
    assert [column.name for column in constraint.columns] == ["broadcast_id", "user_id"]


def test_text_and_photo_payloads_always_open_the_configured_market():
    public_url = "https://market.example/app"
    text_method, text_payload = broadcast_market_payload(
        1, text="Важное сообщение", photo=None, public_url=public_url
    )
    photo_method, photo_payload = broadcast_market_payload(
        1, text="Подпись", photo="photo-id", public_url=public_url
    )
    assert text_method == "sendMessage"
    assert text_payload["text"] == "Важное сообщение"
    assert photo_method == "sendPhoto"
    assert photo_payload["caption"] == "Подпись"
    for payload in (text_payload, photo_payload):
        button = payload["reply_markup"]["inline_keyboard"][0][0]
        assert button["text"] == "🚘 Открыть Market"
        assert button["web_app"]["url"].startswith(public_url)
        assert "af_build=" in button["web_app"]["url"]


def test_broadcast_sender_defensively_parses_retry_after():
    source = (Path(__file__).parents[1] / "app" / "bot.py").read_text(encoding="utf-8")
    assert "except (TypeError, ValueError):" in source
    assert 'BroadcastSendResult(False, "invalid_response"' in source


def test_reliable_migration_releases_legacy_active_job_without_replaying_it():
    migration = (
        Path(__file__).parents[1] / "migrations" / "versions" / "0021_reliable_admin_broadcasts.py"
    ).read_text(encoding="utf-8")
    upgrade = migration.split("def downgrade", 1)[0]
    assert "admin_broadcast_recipients" in upgrade
    assert "legacy_worker_interrupted" in upgrade
    assert "WHERE status IN ('pending', 'running')" in upgrade
    assert "uq_broadcast_recipient_user" in upgrade
    assert "drop_table" not in upgrade


@pytest.mark.asyncio
async def test_rate_limit_is_retried_once_and_never_forever(monkeypatch):
    results = iter([
        BroadcastSendResult(False, "rate_limited", "Too Many Requests", 1),
        BroadcastSendResult(True),
    ])
    calls = []

    async def fake_send(telegram_id, *, text, photo):
        calls.append((telegram_id, text, photo))
        return next(results)

    async def fake_sleep(seconds):
        assert seconds == 1

    monkeypatch.setattr("app.broadcasts.send_broadcast_message", fake_send)
    monkeypatch.setattr("app.broadcasts.asyncio.sleep", fake_sleep)
    result = await send_with_bounded_rate_limit(7, text="Текст", photo=None)
    assert result.success is True
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_blocked_recipient_is_a_result_not_a_worker_exception(monkeypatch):
    async def fake_send(_telegram_id, *, text, photo):
        return BroadcastSendResult(False, "recipient_unavailable", "bot was blocked")

    monkeypatch.setattr("app.broadcasts.send_broadcast_message", fake_send)
    result = await send_with_bounded_rate_limit(8, text="Текст", photo=None)
    assert result.success is False
    assert result.error_type == "recipient_unavailable"
