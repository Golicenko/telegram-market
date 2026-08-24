import pytest

from app import bot
from app.config import Settings
from app.frontend import FRONTEND_BUILD


def test_default_and_private_menu_buttons_use_the_current_versioned_url():
    default = bot.chat_menu_button_payload("https://market.example/")
    private = bot.chat_menu_button_payload("https://market.example/", 123456)

    assert default["menu_button"]["web_app"]["url"] == f"https://market.example/?af_build={FRONTEND_BUILD}"
    assert "chat_id" not in default
    assert private["chat_id"] == 123456
    assert private["menu_button"]["web_app"]["url"] == default["menu_button"]["web_app"]["url"]


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
    assert calls[1][0] == "sendMessage"
