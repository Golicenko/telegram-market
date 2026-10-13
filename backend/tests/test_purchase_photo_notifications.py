"""Telegram transport tests: never send a real bot message or spend production AF."""
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app import message_notifications as delivery
from app.seller_orders import paid_order_body


def job(photo="/api/media/car-photo"):
    return {"ids": [uuid.uuid4()], "telegram_id": 2, "notification_type": "deal_created",
            "text": "🚗 Вашу машину купили — заказ #12345678\nBMW M5 F90\nСумма: 100 AF",
            "params": {"deal_id": str(uuid.uuid4())}, "photo_url": photo}


def transport(monkeypatch, handler):
    monkeypatch.setattr(delivery, "get_settings", lambda: SimpleNamespace(
        bot_token="test-only-secret", externally_reachable_url="https://market.example"))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(delivery.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize("source,expected,error", [
    ("/api/media/car", "https://market.example/api/media/car", None),
    ("uploads/car.jpg", "https://market.example/uploads/car.jpg", None),
    ("https://cdn.example/car.jpg", "https://cdn.example/car.jpg", None),
    ("AgAC" + "a" * 70, "AgAC" + "a" * 70, None),
    (None, None, "photo_missing"),
    ("", None, "photo_missing"),
    ("file:///etc/passwd", None, "photo_scheme_invalid"),
    ("https://name:secret@cdn.example/car", None, "photo_url_invalid"),
    ("https://[invalid", None, "photo_url_invalid"),
    ("/car\n.jpg", None, "photo_reference_invalid"),
])
def test_photo_url_and_file_id_resolution(source, expected, error):
    assert delivery.purchase_photo_reference(source, "https://market.example") == (expected, error)


@pytest.mark.asyncio
@pytest.mark.parametrize("photo", ["/api/media/car-photo", "https://cdn.example/car.jpg", "AgAC" + "a" * 70])
async def test_purchase_uses_one_photo_caption_and_exact_deal_button(monkeypatch, photo):
    calls = []
    def handler(request):
        calls.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.content)))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    transport(monkeypatch, handler)
    event = job(photo)
    assert await delivery.send_delivery(event) == ("sent", None)
    assert len(calls) == 1 and calls[0][0] == "sendPhoto"
    data = calls[0][1]
    assert data["photo"] == delivery.purchase_photo_reference(photo, "https://market.example")[0]
    assert data["caption"] == event["text"] and "text" not in data
    button = data["reply_markup"]["inline_keyboard"][0][0]
    assert button["text"] == "Открыть сделку"
    assert parse_qs(urlsplit(button["web_app"]["url"]).query)["deal_id"] == [event["params"]["deal_id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("photo,reject", [(None, False), ("javascript:bad", False), ("/api/media/missing", True)])
async def test_missing_or_explicitly_rejected_photo_falls_back_once_and_records_reason(monkeypatch, caplog, photo, reject):
    methods = []
    def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        methods.append(method)
        if method == "sendPhoto":
            return httpx.Response(400, json={"ok": False, "error_code": 400,
                "description": "Bad Request: failed to get HTTP URL content https://cdn.example/private?token=test-only-secret"})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 2}})
    transport(monkeypatch, handler)
    status, reason = await delivery.send_delivery(job(photo))
    assert status == "sent" and reason.startswith("photo_fallback:")
    assert methods == (["sendPhoto", "sendMessage"] if reject else ["sendMessage"])
    assert "purchase_photo_" in caplog.text
    assert "test-only-secret" not in caplog.text + reason and "?token=" not in caplog.text + reason


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,expected", [("timeout", "unknown"), ("invalid_json", "unknown"),
    ("server", "unknown"), ("blocked", "blocked"), ("rate", "failed")])
async def test_photo_ambiguous_or_recipient_failure_never_sends_duplicate_text(monkeypatch, failure, expected):
    calls = []
    def handler(request):
        calls.append(request.url.path.rsplit("/", 1)[-1])
        if failure == "timeout":
            raise httpx.ReadTimeout("test timeout", request=request)
        if failure == "invalid_json":
            return httpx.Response(502, text="bad gateway")
        code = {"server": 500, "blocked": 403, "rate": 429}[failure]
        return httpx.Response(code, json={"ok": False, "error_code": code,
            "description": "Forbidden: bot was blocked by the user" if failure == "blocked" else "try later"})
    transport(monkeypatch, handler)
    assert (await delivery.send_delivery(job()))[0] == expected
    assert calls == ["sendPhoto"]


def test_long_unicode_listing_name_keeps_amount_order_and_deadline_in_caption():
    deal = SimpleNamespace(id=uuid.uuid4(), price_af_coins="123.45", seller_delivery_deadline=datetime.now(UTC))
    listing = SimpleNamespace(brand="🚗" * 5000, model="M5", game_version="car_parking_2")
    body = paid_order_body(deal, listing)
    assert len(body.encode("utf-16-le")) // 2 <= 1024
    assert "123.45 AF" in body and str(deal.id)[:8] in body and "Car Parking 2" in body
