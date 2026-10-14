import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app import message_notifications
from app.schemas import SupportTicketCreate
from app.support_catalog import CATEGORIES, ticket_notice, topic_label
from test_purchase_photo_notifications import transport


@pytest.mark.parametrize("key,icon,label,related", CATEGORIES)
def test_categories_and_legacy_case(key, icon, label, related):
    assert topic_label(key.upper()) == label
    assert SupportTicketCreate(topic=key, message="Помогите").topic == key


@pytest.mark.parametrize("old,expected", [("PAYMENT_ISSUE", "Оплата и баланс"), ("TRANSACTION_PROBLEM", "Проблема со сделкой"), ("Проблема по сделке", "Проблема со сделкой"), ("Вывод #000057", "Вывод #000057")])
def test_old_ticket_topics(old, expected):
    assert topic_label(old) == expected


def test_new_invalid_category_rejected_without_rewriting_old_history():
    with pytest.raises(ValidationError):
        SupportTicketCreate(topic="invented", message="test")


@pytest.mark.asyncio
@pytest.mark.parametrize("username", ["example", None, "bad/?query=1"])
async def test_notice_long_text_plain_html_and_real_buttons(monkeypatch, username):
    ticket = SimpleNamespace(id=uuid.uuid4(), deal_id=uuid.uuid4(), topic="WITHDRAWAL")
    author = SimpleNamespace(username=username, first_name="<b>Имя</b>", last_name=None)
    body = ticket_notice(ticket, author, "<script>опасный текст</script>" * 140)
    assert len(body) < 1500 and "Вывод средств" in body
    assert ("@example" if username == "example" else "Username отсутствует") in body
    calls = []
    def telegram(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    transport(monkeypatch, telegram)
    job = {"telegram_id": 1, "text": body, "notification_type": "support_ticket", "params": {"support_case": str(ticket.id)},
           "contact_url": "https://t.me/example" if username == "example" else "tg://user?id=123",
           "linked_deal_id": str(ticket.deal_id)}
    assert await message_notifications.send_delivery(job) == ("sent", None)
    assert len(calls) == 1 and "parse_mode" not in calls[0]
    buttons = [button for row in calls[0]["reply_markup"]["inline_keyboard"] for button in row]
    assert [button["text"] for button in buttons] == ["Открыть обращение", "Написать пользователю", "Связаться через бота", "Открыть заказ"]
    assert f"support_case={ticket.id}" in buttons[0]["web_app"]["url"]
    assert "contact=1" in buttons[2]["web_app"]["url"]
    assert f"admin_deal_id={ticket.deal_id}" in buttons[3]["web_app"]["url"]
