"""Isolated PostgreSQL tests; Telegram transport is simulated, never a live charge."""
import asyncio
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select, text

from app import publications
from app.config import Settings, get_settings
from app.models import ConversationMessage, Listing, PublicationDraft, StarPayment, User, Wallet, WalletTransaction
from app.schemas import ListingCreate
from app.services import create_listing
from test_catalog_and_acceptance_postgres import client_app, headers
from test_referral_bonus_postgres import isolated_pg, signed_login, apply_revisions
from test_seller_orders_postgres import paid_order


def listing_payload(index=0):
    return ListingCreate(client_request_id=uuid.uuid4(), game_version="car_parking_1" if index % 2 else "car_parking_2",
                         brand="Test car", model="M", power_hp=10, max_speed_kph=20, description="Test", price_af_coins=10, image_urls=["/test.jpg"])


def app(sessions):
    result = client_app(sessions)
    result.include_router(publications.router)
    return result


def payment(draft, charge=None):
    return {"currency": "XTR", "total_amount": draft["price_stars"], "invoice_payload": publications.PREFIX + draft["id"], "telegram_payment_charge_id": charge or str(uuid.uuid4())}


async def seed_slots(session, user, count):
    (await session.get(User, user.id)).publication_count = count
    for n in range(count):
        payload = listing_payload(n)
        session.add(Listing(seller_id=user.id, listing_type="regular", status="active", **payload.model_dump(exclude={"image_urls", "promote_for_24h"})))


@pytest.mark.asyncio
async def test_five_active_shared_slots_sixth_seventh_stars_no_af_or_referrals(monkeypatch):
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 88101)
        other = await signed_login(sessions, 88102)
        invoice_calls = []
        async def telegram(method, payload):
            assert method == "createInvoiceLink"
            invoice_calls.append(payload)
            return {"result": "https://t.me/$isolated-test-invoice"}
        monkeypatch.setattr(publications, "call_bot_api", telegram)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app(sessions)), base_url="http://test") as client:
            ids = []
            for n in range(5):
                payload = listing_payload(n).model_dump(mode="json")
                response = await client.post("/api/listings", headers=headers(user), json=payload)
                assert response.status_code == 201, response.text
                ids.append(response.json()["id"])
                assert (await client.post("/api/listings", headers=headers(user), json=payload)).json()["id"] == ids[-1]
            rules = (await client.get("/api/publication-rules", headers=headers(user))).json()
            assert rules["used"] == 5 and rules["remaining"] == 0
            for n in (6, 7):
                payload = listing_payload(n).model_dump(mode="json")
                assert (await client.post("/api/listings", headers=headers(user), json=payload)).status_code == 402
                response = await client.post("/api/publication-drafts", headers=headers(user), json=payload)
                assert response.status_code == 200, response.text
                draft = response.json()
                assert draft["price_stars"] == 5 and draft["status"] == "draft"
                endpoint = f'/api/publication-drafts/{draft["id"]}'
                assert (await client.get(endpoint, headers=headers(other))).status_code == 404
                for _ in range(2):
                    assert (await client.post(endpoint + "/invoice", headers=headers(user))).status_code == 200
                # Closing checkout has no write and no publication.
                assert (await client.get(endpoint, headers=headers(user))).json()["listing_id"] is None
                async with sessions() as session:
                    assert (await publications.validate_checkout(session, other.telegram_id, publications.PREFIX + draft["id"], "XTR", 5, "wrong"))[0] is False
                    assert (await publications.validate_checkout(session, user.telegram_id, publications.PREFIX + draft["id"], "XTR", 4, "amount"))[0] is False
                    assert (await publications.validate_checkout(session, user.telegram_id, publications.PREFIX + draft["id"], "XTR", 5, str(n)))[0] is True
                    assert (await publications.validate_checkout(session, user.telegram_id, publications.PREFIX + draft["id"], "XTR", 5, "concurrent"))[0] is False
                receipt = payment(draft)
                async def deliver():
                    async with sessions() as session:
                        draft_id = await publications.receive_payment(session, user.telegram_id, receipt)
                        await publications.fulfill(session, draft_id)
                await asyncio.gather(deliver(), deliver(), deliver())
                published = (await client.get(endpoint, headers=headers(user))).json()
                assert published["status"] == "published" and published["listing_id"]
            assert len(invoice_calls) == 2 and all(item["currency"] == "XTR" and item["prices"][0]["amount"] == 5 for item in invoice_calls)
        async with sessions() as session:
            assert (await session.get(User, user.id)).publication_count == 7
            assert await session.scalar(select(func.count()).select_from(StarPayment)) == 2
            assert await session.scalar(select(func.sum(StarPayment.af_coin_amount))) == 0
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 0
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == user.id))).available_balance == 0


@pytest.mark.asyncio
async def test_last_free_slot_race_and_failed_pin_does_not_consume_slot():
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 88201)
        async with sessions() as session, session.begin():
            await seed_slots(session, user, 4)
        async def publish():
            async with sessions() as session:
                try:
                    await create_listing(session, user, listing_payload(), listing_type="regular")
                    return 201
                except Exception as error:
                    return getattr(error, "status_code", 500)
        assert sorted(await asyncio.gather(publish(), publish())) == [201, 402]
        other = await signed_login(sessions, 88202)
        async with sessions() as session:
            with pytest.raises(Exception) as error:
                await create_listing(session, other, listing_payload(), listing_type="regular", pinned=True)
            assert error.value.status_code == 402
        async with sessions() as session:
            assert (await session.get(User, other.id)).publication_count == 0


@pytest.mark.asyncio
async def test_real_webhook_route_secret_owner_frozen_amount_and_admin_settings(monkeypatch):
    from app import routes
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 88701)
        admin = await signed_login(sessions, 88702)
        async with sessions() as session, session.begin():
            await seed_slots(session, user, 5)
        application = app(sessions)
        settings = Settings(bot_token="referral-test-token", admin_id=admin.telegram_id, debug=False)
        application.dependency_overrides[get_settings] = lambda: settings
        answers = []
        async def answer(query_id, ok, error):
            answers.append(ok)
        monkeypatch.setattr(routes, "answer_pre_checkout_query", answer)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            draft = (await client.post("/api/publication-drafts", headers=headers(user), json=listing_payload().model_dump(mode="json"))).json()
            updated = await client.put("/api/admin/publication-rules", headers=headers(admin), json={"free_limit": 5, "price_stars": 8, "enabled": True, "reason": "Frozen price check"})
            assert updated.status_code == 200, updated.text
            hook = {"pre_checkout_query": {"id": "checkout", "from": {"id": user.telegram_id}, "invoice_payload": publications.PREFIX + draft["id"], "currency": "XTR", "total_amount": 5}}
            assert (await client.post("/api/telegram/webhook", json=hook)).status_code == 403
            trusted = {"X-Telegram-Bot-Api-Secret-Token": settings.effective_telegram_webhook_secret}
            assert (await client.post("/api/telegram/webhook", headers=trusted, json=hook)).status_code == 200
            assert answers == [True]
            receipt = {"message": {"from": {"id": user.telegram_id}, "successful_payment": payment(draft)}}
            for _ in range(2):
                response = await client.post("/api/telegram/webhook", headers=trusted, json=receipt)
                assert response.status_code == 200, response.text
            stored = (await client.get('/api/publication-drafts/' + draft['id'], headers=headers(user))).json()
            assert stored["status"] == "published"
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(StarPayment)) == 1
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 0


@pytest.mark.asyncio
async def test_price_snapshot_paid_recovery_and_admin_refund(monkeypatch):
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 88301)
        admin = await signed_login(sessions, 88302)
        async with sessions() as session, session.begin():
            await seed_slots(session, user, 5)
            (await session.scalar(select(Wallet).where(Wallet.user_id == user.id))).purchased_balance = 5
        payload = listing_payload()
        payload.promote_for_24h = True
        async with sessions() as session:
            draft = await publications.create_draft(payload, user, session)
        async with sessions() as session, session.begin():
            (await session.scalar(select(Wallet).where(Wallet.user_id == user.id))).purchased_balance = 0
        async with sessions() as session:
            await publications.update_rules(publications.RulesUpdate(free_limit=5, price_stars=9, enabled=True, reason="Test change"), admin, session)
        async with sessions() as session:
            assert (await publications.validate_checkout(session, user.telegram_id, publications.PREFIX + draft["id"], "XTR", 5, "query"))[0]
            await publications.receive_payment(session, user.telegram_id, payment(draft))
            await publications.fulfill(session, uuid.UUID(draft["id"]))  # Pin shortfall leaves receipt durable.
        async with sessions() as session:
            stored = await session.get(PublicationDraft, uuid.UUID(draft["id"]))
            assert stored.status == "paid" and stored.payment_id and not stored.listing_id
            assert (await session.get(User, user.id)).publication_count == 5
        calls = []
        async def telegram(method, params):
            calls.append((method, params))
            return {"result": True}
        monkeypatch.setattr(publications, "call_bot_api", telegram)
        for _ in range(2):
            async with sessions() as session:
                result = await publications.admin_refund(uuid.UUID(draft["id"]), publications.Resolution(reason="Cannot publish"), admin, session)
                assert result["status"] == "refunded"
        assert len(calls) == 1 and calls[0][0] == "refundStarPayment"
        # Another paid draft survives worker restart and publishes without a new invoice.
        payload = listing_payload()
        async with sessions() as session:
            draft = await publications.create_draft(payload, user, session)
        async with sessions() as session:
            await publications.receive_payment(session, user.telegram_id, payment(draft))
        async with sessions() as session:
            await publications.fulfill(session, uuid.UUID(draft["id"]))
        async with sessions() as session:
            assert (await session.get(PublicationDraft, uuid.UUID(draft["id"]))).status == "published"


@pytest.mark.asyncio
async def test_message_pagination_1000_access_and_duplicate_send():
    async with isolated_pg() as (_, sessions):
        buyer, seller, _, deal = await paid_order(sessions)
        stranger = await signed_login(sessions, 88403)
        when = datetime.now(UTC)
        async with sessions() as session, session.begin():
            for n in range(1000):
                session.add(ConversationMessage(id=uuid.UUID(int=n+1), conversation_id=deal.conversation_id, deal_id=deal.id, sender_id=seller.id, body=f"Text {n} <script>bad</script>", message_type="text", created_at=when))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app(sessions)), base_url="http://test") as client:
            path = f"/api/conversations/{deal.conversation_id}/messages"
            assert (await client.get(path, headers=headers(stranger))).status_code == 404
            query = {"deal_id": str(deal.id)}
            ids = []
            for _ in range(10):
                response = await client.get(path, headers=headers(buyer), params=query)
                assert response.status_code == 200, response.text
                page = response.json()
                assert len(page) == 100
                ids.extend(item["id"] for item in page)
                query["before"] = page[0]["id"]
            assert len(set(ids)) == 1000
            data = {"body": "Repeated request", "client_message_id": str(uuid.uuid4()), "deal_id": str(deal.id)}
            responses = await asyncio.gather(*[client.post(path, headers=headers(buyer), json=data) for _ in range(3)])
            assert all(response.status_code == 201 for response in responses)
            assert len({response.json()["id"] for response in responses}) == 1
            assert (await client.post(path, headers=headers(stranger), json=data)).status_code == 404
            assert (await client.put("/api/admin/publication-rules", headers=headers(buyer), json={"free_limit": 99, "price_stars": 1, "enabled": False, "reason": "bypass"})).status_code == 403


@pytest.mark.asyncio
async def test_paid_draft_cannot_bypass_refund_lock_or_reuse_extra_charge(monkeypatch):
    from fastapi import HTTPException
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 88601)
        admin = await signed_login(sessions, 88602)
        async with sessions() as session, session.begin():
            await seed_slots(session, user, 5)
        payload = listing_payload()
        async with sessions() as session:
            draft = await publications.create_draft(payload, user, session)
        draft_id = uuid.UUID(draft["id"])
        async with sessions() as session:
            await publications.receive_payment(session, user.telegram_id, payment(draft))
        # Publication request is already paid; disabling the fee does not bypass it.
        async with sessions() as session:
            await publications.update_rules(publications.RulesUpdate(free_limit=5, price_stars=9, enabled=False, reason="Pause rollout"), admin, session)
        async with sessions() as session:
            with pytest.raises(HTTPException) as error:
                await create_listing(session, user, payload, listing_type="regular")
            assert error.value.status_code == 402
        async with sessions() as stale:
            cached = await stale.get(PublicationDraft, draft_id)
            assert cached.status == "paid"
            await stale.commit()
            async with sessions() as other, other.begin():
                (await other.get(PublicationDraft, draft_id)).status = "refund_pending"
            with pytest.raises(HTTPException) as error:
                await create_listing(stale, user, payload, listing_type="regular", publication_id=draft_id)
            assert error.value.status_code == 409  # Row lock must refresh cached status.
        extra = payment(draft)
        async with sessions() as session:
            await publications.receive_payment(session, user.telegram_id, extra)
        async with sessions() as session:
            receipt = await session.scalar(select(StarPayment).where(StarPayment.telegram_payment_charge_id == extra["telegram_payment_charge_id"]))
            assert receipt.status == "publication_review" and receipt.af_coin_amount == 0
            assert await session.scalar(select(func.count()).select_from(Listing)) == 5
            assert await session.scalar(select(func.count()).select_from(Listing).where(Listing.client_request_id == payload.client_request_id)) == 0
        calls = []
        async def refund(method, params):
            calls.append(params)
            return {"result": True}
        monkeypatch.setattr(publications, "call_bot_api", refund)
        for _ in range(2):
            async with sessions() as session:
                await publications.refund_extra(receipt.id, publications.Resolution(reason="Duplicate charge"), admin, session)
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_migration_counts_retained_history_including_deleted():
    async with isolated_pg(tables=False) as (engine, _):
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: apply_revisions(sync, target="0048_catalog_baseline"))
            user_id = uuid.uuid4()
            await conn.execute(text("INSERT INTO users(id,telegram_id,first_name,role,is_blocked) VALUES (:id,88501,'Test','user',false)"), {"id": user_id})
            for status in ("active", "sold", "deleted", "paused"):
                await conn.execute(text("""INSERT INTO listings(id,seller_id,listing_type,game_version,status,brand,model,power_hp,max_speed_kph,description,price_af_coins)
                    VALUES (:id,:user,'regular','car_parking_1',:status,'Test','M',1,1,'Test',10)"""), {"id": uuid.uuid4(), "user": user_id, "status": status})
            await conn.run_sync(lambda sync: apply_revisions(sync, target="head", after="0048_catalog_baseline"))
            assert await conn.scalar(text("SELECT publication_count FROM users")) == 4
            assert await conn.scalar(text("SELECT count(*) FROM publication_drafts")) == 0
            assert await conn.scalar(text("SELECT count(*) FROM star_payments")) == 0
