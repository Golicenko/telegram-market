import uuid
from pathlib import Path

import pytest
from fastapi import BackgroundTasks

from app import bot, routes
from app.config import Settings
from app.frontend import FRONTEND_BUILD
from app.models import User, Wallet


def test_default_and_private_menu_buttons_use_the_current_versioned_url():
    default = bot.chat_menu_button_payload("https://market.example/")
    private = bot.chat_menu_button_payload("https://market.example/", 123456)

    assert default["menu_button"]["web_app"]["url"] == f"https://market.example/?af_build={FRONTEND_BUILD}"
    assert "chat_id" not in default
    assert private["chat_id"] == 123456
    assert private["menu_button"]["web_app"]["url"] == default["menu_button"]["web_app"]["url"]


@pytest.mark.asyncio
async def test_training_share_uses_main_mini_app_start_parameter(monkeypatch):
    calls = []

    async def fake_call(method, payload):
        calls.append((method, payload))
        return {"ok": True, "result": {"username": "AutoFlowMarketBot"}}

    monkeypatch.setattr(bot, "call_bot_api", fake_call)
    monkeypatch.setattr(bot, "_bot_username_cache", None)
    product_id = str(uuid.uuid4())
    assert await bot.training_mini_app_link(product_id) == f"https://t.me/AutoFlowMarketBot?startapp=training_{product_id}"
    assert calls == [("getMe", {})]


@pytest.mark.asyncio
async def test_send_menu_refreshes_the_users_private_menu_button(monkeypatch):
    calls = []

    async def fake_call(method, payload):
        calls.append((method, payload))
        return {"ok": True}

    monkeypatch.setattr(bot, "get_settings", lambda: Settings(bot_token="token", public_base_url="https://market.example"))
    monkeypatch.setattr(bot, "call_bot_api", fake_call)

    assert await bot.send_bot_menu(123456) is True
    assert calls[0][0] == "setChatMenuButton"
    assert calls[0][1]["chat_id"] == 123456
    assert f"af_build={FRONTEND_BUILD}" in calls[0][1]["menu_button"]["web_app"]["url"]
    assert calls[1][0] == "sendPhoto"
    assert calls[1][1]["caption"] == bot.START_MENU_TEXT
    keyboard = calls[1][1]["reply_markup"]["inline_keyboard"]
    assert len(keyboard) == 1
    assert keyboard[0][0]["text"] == "🚘 Открыть маркетплейс"
    assert keyboard[0][0]["web_app"]["url"].startswith("https://market.example")
    assert calls[1][1]["photo"].startswith("https://market.example/images/autoflow-start.png")


@pytest.mark.asyncio
async def test_repeated_start_sends_one_photo_and_one_web_app_button_each_time(monkeypatch):
    calls = []

    async def fake_call(method, payload):
        calls.append((method, payload))
        return {"ok": True}

    monkeypatch.setattr(bot, "get_settings", lambda: Settings(bot_token="token", public_base_url="https://market.example"))
    monkeypatch.setattr(bot, "configure_chat_menu_button", lambda _telegram_id: async_true())
    monkeypatch.setattr(bot, "call_bot_api", fake_call)

    assert await bot.send_bot_menu(123456) is True
    assert await bot.send_bot_menu(123456) is True
    assert [method for method, _payload in calls] == ["sendPhoto", "sendPhoto"]
    assert all(len(payload["reply_markup"]["inline_keyboard"]) == 1 for _method, payload in calls)


async def async_true():
    return True


class StartSession:
    def __init__(self, user=None):
        self.user = user
        self.added = []
        self.commits = 0

    async def scalar(self, _query):
        return self.user

    def add(self, value):
        self.added.append(value)
        if isinstance(value, User):
            self.user = value

    async def flush(self):
        if self.user and self.user.id is None:
            self.user.id = uuid.uuid4()

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_start_works_for_new_and_existing_users_and_repeat_requests():
    settings = Settings(bot_token="test-token")
    secret = settings.effective_telegram_webhook_secret
    update = {"message": {"from": {"id": 77, "first_name": "Buyer"}, "text": "/start"}}

    new_session = StartSession()
    new_tasks = BackgroundTasks()
    assert await routes.telegram_webhook(update, new_tasks, secret, new_session, settings) == {"ok": True}
    assert new_session.user.bot_started is True
    assert any(isinstance(item, Wallet) for item in new_session.added)
    assert len(new_tasks.tasks) == 1
    assert new_tasks.tasks[0].func is routes.send_bot_menu

    new_session.user.bot_started = False
    for _ in range(2):
        repeat_tasks = BackgroundTasks()
        assert await routes.telegram_webhook(update, repeat_tasks, secret, new_session, settings) == {"ok": True}
        assert new_session.user.bot_started is True
        assert len(repeat_tasks.tasks) == 1
        assert repeat_tasks.tasks[0].func is routes.send_bot_menu


def test_start_photo_is_packaged_and_accepted_by_telegram_size_limit():
    path = Path(__file__).parents[2] / "webapp" / "images" / "autoflow-start.png"
    assert path.is_file()
    assert 0 < path.stat().st_size < 10 * 1024 * 1024
