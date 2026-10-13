"""Real HTTP purchase + isolated PostgreSQL outbox; Telegram transport is simulated."""
import asyncio
import json
import uuid
from datetime import UTC, datetime
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from PIL import Image
from sqlalchemy import delete, func, select

from app import message_notifications as delivery
from app.config import Settings
from app.models import Deal, Listing, ListingImage, Notification, User, Wallet, WalletTransaction
from test_catalog_and_acceptance_postgres import client_app, headers
from test_referral_bonus_postgres import isolated_pg, signed_login
from test_seller_orders_postgres import paid_order


@pytest.mark.asyncio
@pytest.mark.parametrize("game", ["car_parking_1", "car_parking_2"])
@pytest.mark.parametrize("outcome", ["photo", "fallback", "unknown"])
async def test_paid_purchase_snapshot_restart_delivery_and_duplicate_requests(monkeypatch, game, outcome):
    async with isolated_pg() as (_, sessions):
        buyer = await signed_login(sessions, 99201)
        seller = await signed_login(sessions, 99202)
        outsider = await signed_login(sessions, 99203)
        async with sessions() as session, session.begin():
            (await session.get(User, seller.id)).bot_started = True
            (await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))).purchased_balance = 100
        application = client_app(sessions)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="https://market.example") as client:
            # Exercise the existing upload/normalization/public retrieval, not a made-up media URL.
            buffer = BytesIO()
            Image.new("RGB", (80, 60), "navy").save(buffer, format="PNG")
            uploaded = await client.post("/api/uploads", headers=headers(seller), files={"file": ("test-car.png", buffer.getvalue(), "image/png")})
            assert uploaded.status_code == 201, uploaded.text
            first_photo = uploaded.json()["url"]
            assert (await client.get(first_photo)).headers["content-type"].startswith("image/")
            async with sessions() as session, session.begin():
                listing = Listing(seller_id=seller.id, game_version=game, listing_type="regular", status="active",
                    brand="BMW", model="M5 F90", power_hp=100, max_speed_kph=200, description="Isolated test", price_af_coins=100)
                other = Listing(seller_id=seller.id, game_version=game, listing_type="regular", status="active",
                    brand="Other", model="", power_hp=1, max_speed_kph=1, description="Other", price_af_coins=50)
                session.add_all([listing, other])
                await session.flush()
                session.add_all([ListingImage(listing_id=other.id, position=0, url="/wrong-car.jpg"),
                    ListingImage(listing_id=listing.id, position=1, url="/second-photo.jpg"),
                    ListingImage(listing_id=listing.id, position=0, url=first_photo)])
            replies = await asyncio.gather(*(client.post(f"/api/listings/{listing.id}/purchase", headers=headers(buyer)) for _ in range(3)))
            assert all(reply.status_code == 200 for reply in replies), [r.text for r in replies]
            assert len({r.json()["id"] for r in replies}) == 1
            deal_id = uuid.UUID(replies[0].json()["id"])
            async with sessions() as session, session.begin():
                notice = await session.scalar(select(Notification).where(Notification.notification_type == "deal_created"))
                assert notice.payload["sale_snapshot"]["photo_url"] == first_photo
                assert notice.payload["sale_snapshot"]["listing_id"] == str(listing.id)
                # Simulate later editing/soft deletion before a restarted worker sends.
                stored = await session.get(Listing, listing.id)
                stored.brand, stored.price_af_coins, stored.deleted_at = "Changed", 999, datetime.now(UTC)
                await session.execute(delete(ListingImage).where(ListingImage.listing_id == listing.id))
                session.add(ListingImage(listing_id=listing.id, position=0, url="/replacement.jpg"))
            assert (await client.get(first_photo)).status_code == 200
            # Existing protected deal route is the destination of the actual inline button.
            assert (await client.get(f"/api/deals/{deal_id}", headers=headers(seller))).status_code == 200
            assert (await client.get(f"/api/deals/{deal_id}", headers=headers(outsider))).status_code in {403, 404}

        calls = []
        def telegram(request):
            method = request.url.path.rsplit("/", 1)[-1]
            data = json.loads(request.content)
            calls.append((method, data))
            if outcome == "unknown":
                raise httpx.ReadTimeout("lost response", request=request)
            if outcome == "fallback" and method == "sendPhoto":
                return httpx.Response(400, json={"ok": False, "error_code": 400, "description": "Bad Request: wrong file identifier/HTTP URL specified"})
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})
        real_client = httpx.AsyncClient
        monkeypatch.setattr(delivery.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(telegram), **kw))
        monkeypatch.setattr(delivery, "get_settings", lambda: Settings(bot_token="test-only", public_base_url="https://market.example"))
        monkeypatch.setattr(delivery, "SessionLocal", sessions)
        await asyncio.gather(delivery.recover_message_notifications(), delivery.recover_message_notifications())
        await delivery.recover_message_notifications()
        assert [method for method, _ in calls] == (["sendPhoto", "sendMessage"] if outcome == "fallback" else ["sendPhoto"])
        data = calls[0][1]
        assert data["photo"] == "https://market.example" + first_photo
        assert "BMW M5 F90" in data["caption"] and "100.00 AF" in data["caption"]
        assert str(deal_id)[:8] in data["caption"] and "999" not in data["caption"]
        assert ("Car Parking 1" if game.endswith("1") else "Car Parking 2") in data["caption"]
        button = data["reply_markup"]["inline_keyboard"][0][0]
        assert button["text"] == "Открыть сделку"
        assert parse_qs(urlsplit(button["web_app"]["url"]).query)["deal_id"] == [str(deal_id)]
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Deal)) == 1
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 1
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "deal_created")) == 1
            notice = await session.scalar(select(Notification).where(Notification.notification_type == "deal_created"))
            assert notice.delivery_status == ("unknown" if outcome == "unknown" else "sent")
            if outcome == "fallback":
                assert notice.delivery_error.startswith("photo_fallback:")
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            assert wallet.available_balance == 0 and wallet.frozen_balance == 100
            assert (await session.get(Deal, deal_id)).status == "paid"


@pytest.mark.asyncio
async def test_legacy_pending_notice_gets_only_its_own_photo_and_sent_is_not_replayed():
    async with isolated_pg() as (_, sessions):
        _, seller, listing, deal = await paid_order(sessions)
        async with sessions() as session, session.begin():
            notice = await session.scalar(select(Notification).where(Notification.notification_type == "deal_created"))
            notice.payload = {"deal_id": str(deal.id)}  # Pre-fix pending row, no snapshot.
            session.add(ListingImage(listing_id=listing.id, position=0, url="/legacy-car.jpg"))
        async with sessions() as session:
            event = await delivery.claim_delivery(session, seller.id, datetime.now(UTC))
        assert event["photo_url"] == "/legacy-car.jpg"
        async with sessions() as session, session.begin():
            notice = await session.get(Notification, event["ids"][0])
            assert notice.payload["photo_snapshot_source"] == "legacy_listing"
            notice.delivery_status = "sent"
        async with sessions() as session:
            assert await delivery.claim_delivery(session, seller.id, datetime.now(UTC)) is None
