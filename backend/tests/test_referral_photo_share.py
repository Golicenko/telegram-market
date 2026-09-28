"""Photo invitation contract, persistent cache and the real public asset route.

Telegram transport is isolated: these are not live two-account Telegram tests.
"""

import hashlib
import time
from datetime import UTC, datetime, timedelta
from io import BytesIO

import httpx
import pytest
from fastapi import HTTPException, Response
from PIL import Image

from app import referral_routes, referrals
from app.config import Settings
from app.frontend import WEBAPP_DIR
from app.models import ReferralShare
from test_referrals import db as referral_db_fixture, login


db = referral_db_fixture


@pytest.fixture
def photo_transport(monkeypatch):
    calls = []

    async def url(code):
        return "https://t.me/ActualBot?startapp=" + code

    async def bot(method, payload):
        assert method == "savePreparedInlineMessage"
        calls.append(payload)
        return {"result": {
            "id": f"prepared-{len(calls)}",
            "expiration_date": int(time.time()) + 3600,
        }}

    monkeypatch.setattr(referral_routes, "referral_url", url)
    monkeypatch.setattr(referral_routes, "call_bot_api", bot)
    monkeypatch.setattr(referral_routes, "get_settings", lambda: Settings(
        public_base_url="https://market.example", _env_file=None,
    ))
    return calls


def test_owner_photo_is_unchanged_and_telegram_compatible():
    asset = WEBAPP_DIR / referral_routes.REFERRAL_PHOTO_PATH.lstrip("/")
    original = asset.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    assert digest == "ffadf191b10cd7e3bb87a26a89c07e5ff07ccac843e5230021f342af7d17eb4c"
    assert digest[:12] in asset.name
    assert len(original) == 129764 and len(original) < 5 * 1024 * 1024
    with Image.open(BytesIO(original)) as photo:
        assert photo.format == "JPEG" and photo.size == (960, 1280)
        photo.verify()


@pytest.mark.asyncio
async def test_photo_is_publicly_served_as_jpeg_without_telegram_auth():
    from app.main import app

    # ASGITransport does not start production workers/lifespan.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://market.example"
    ) as client:
        response = await client.get(referral_routes.REFERRAL_PHOTO_PATH)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.content == (
            WEBAPP_DIR / referral_routes.REFERRAL_PHOTO_PATH.lstrip("/")
        ).read_bytes()
        repeated = await client.get(
            referral_routes.REFERRAL_PHOTO_PATH,
            headers={"If-None-Match": response.headers["etag"]},
        )
        assert repeated.status_code == 304


@pytest.mark.parametrize("name", [None, "", "   ", "Telegram User"])
def test_caption_without_name_has_neutral_heading(name):
    assert referrals.invitation_text(name) == (
        "Тебя приглашают в AutoFlow Market 🚗\n\n"
        "Зарабатывай вместе со мной в AutoFlow Market.\n\n"
        "Покупай и продавай машины из Car Parking 1 и Car Parking 2, "
        "приглашай друзей и получай бонусы."
    )


def test_caption_uses_first_name_as_plain_text_and_fits_photo_limit():
    assert referrals.invitation_text("Максим <&>").startswith(
        "Максим <&> приглашает тебя в AutoFlow Market 🚗\n\n"
    )
    text = referrals.invitation_text("🚗" * 1500)
    assert len(text.encode("utf-16-le")) // 2 <= 1024
    assert "Car Parking 1 и Car Parking 2" in text


@pytest.mark.parametrize("base", [None, "http://market.example", "https://localhost", "https://127.0.0.1", "https://user:secret@market.example", "https://market.example/?token=secret"])
def test_photo_requires_configured_public_https_url(monkeypatch, base):
    monkeypatch.setattr(referral_routes, "get_settings", lambda: Settings(
        public_base_url=base, railway_public_domain=None, _env_file=None,
    ))
    with pytest.raises(HTTPException) as error:
        referral_routes.referral_photo_url()
    assert error.value.status_code == 503
    assert "secret" not in error.value.detail


def test_photo_uses_existing_railway_public_domain(monkeypatch):
    monkeypatch.setattr(referral_routes, "get_settings", lambda: Settings(
        public_base_url=None, railway_public_domain="example.up.railway.app", _env_file=None,
    ))
    assert referral_routes.referral_photo_url() == (
        "https://example.up.railway.app" + referral_routes.REFERRAL_PHOTO_PATH
    )


def test_missing_photo_fails_instead_of_sending_text_only(monkeypatch, tmp_path, photo_transport):
    monkeypatch.setattr(referral_routes, "WEBAPP_DIR", tmp_path)
    with pytest.raises(HTTPException) as error:
        referral_routes.referral_photo_url()
    assert error.value.status_code == 503
    assert not photo_transport


@pytest.mark.asyncio
async def test_different_senders_get_their_own_photo_button(db, photo_transport):
    first, second = await login(db, 1), await login(db, 2)
    for user in (first, second):
        result = await referral_routes.prepare_referral_share(Response(), user, db)
        assert result["preparedMessageId"]
    assert len(photo_transport) == 2
    buttons = []
    for payload, user in zip(photo_transport, (first, second)):
        assert payload["user_id"] == user.telegram_id
        photo = payload["result"]
        assert photo["type"] == "photo"
        assert photo["photo_url"] == photo["thumbnail_url"]
        assert photo["caption"] == referrals.invitation_text(user.first_name)
        assert "input_message_content" not in photo and "parse_mode" not in photo
        button = photo["reply_markup"]["inline_keyboard"]
        assert button == [[{"text": "Перейти в маркет", "url":
            "https://t.me/ActualBot?startapp=" + user.referral_code}]]
        buttons.append(button)
    assert buttons[0] != buttons[1]


@pytest.mark.asyncio
async def test_photo_cache_survives_reopen_and_replaces_old_article(db, photo_transport):
    user = await login(db, 1)
    url = "https://t.me/ActualBot?startapp=" + user.referral_code
    caption = referrals.invitation_text(user.first_name)
    db.add(ReferralShare(
        user_id=user.id, prepared_message_id="old-text-only",
        content_hash=hashlib.sha256(f"{url}\n{caption}".encode()).hexdigest(),
        requested_at=datetime.now(UTC) - timedelta(minutes=1),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    ))
    await db.commit()
    first = await referral_routes.prepare_referral_share(Response(), user, db)
    assert first == {"preparedMessageId": "prepared-1"}
    db.session.close()  # Reopen the same DB; no process-local prepared-message cache.
    reopened = await login(db, 1)
    assert await referral_routes.prepare_referral_share(Response(), reopened, db) == first
    assert len(photo_transport) == 1


@pytest.mark.asyncio
async def test_replacing_photo_invalidates_prepared_message(db, monkeypatch, photo_transport):
    user = await login(db, 1)
    await referral_routes.prepare_referral_share(Response(), user, db)
    cached = db.session.get(ReferralShare, user.id)
    cached.requested_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()
    monkeypatch.setattr(referral_routes, "referral_photo_url", lambda:
        "https://market.example/images/referral-share.changed.jpg")
    second = await referral_routes.prepare_referral_share(Response(), user, db)
    assert second == {"preparedMessageId": "prepared-2"}
    assert len(photo_transport) == 2
    assert photo_transport[-1]["result"]["photo_url"].endswith("referral-share.changed.jpg")
