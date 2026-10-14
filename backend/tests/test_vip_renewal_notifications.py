import json
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app import message_notifications as delivery
from test_purchase_photo_notifications import transport


@pytest.mark.asyncio
async def test_real_inline_webapp_button_targets_exact_renewal(monkeypatch):
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    transport(monkeypatch, handler)
    renewal = str(uuid.uuid4())
    job = {"ids": [uuid.uuid4()], "telegram_id": 123, "text": "VIP закончился: BMW M5",
           "notification_type": "vip_expired", "params": {"vip_renewal": renewal}}
    assert await delivery.send_delivery(job) == ("sent", None)
    assert len(calls) == 1
    button = calls[0]["reply_markup"]["inline_keyboard"][0][0]
    assert button["text"] == "Продлить VIP"
    assert parse_qs(urlsplit(button["web_app"]["url"]).query)["vip_renewal"] == [renewal]
