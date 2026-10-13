"""Real PostgreSQL, signed Telegram test identities, isolated database only."""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import func, select, text

from app.config import Settings, get_settings
from app.database import get_session
from app.models import Deal, DealEvent, Listing, Notification, TrainingProduct, User, Wallet, WalletTransaction
from app.routes import router
from app.services import (cancel_deal, set_listing_publication, set_training_product_state,
    auto_cancel_unanswered_deal, auto_cancel_undelivered_deal, create_deal_support_case, update_training_product)
from app.schemas import TrainingProductUpdate
from test_referral_bonus_postgres import isolated_pg, signed_login, apply_revisions
from test_referrals import init_data
from test_seller_orders_postgres import paid_order


def client_app(sessions):
    app = FastAPI()
    app.include_router(router)
    async def database():
        async with sessions() as session:
            yield session
    app.dependency_overrides[get_session] = database
    app.dependency_overrides[get_settings] = lambda: Settings(bot_token="referral-test-token", debug=False)
    return app


def headers(user):
    return {"X-Telegram-Init-Data": init_data(user.telegram_id)}


async def draft(sessions, admin, section):
    async with sessions() as session, session.begin():
        item = (TrainingProduct(admin_id=admin.id, title="Course", short_description="Short", full_description="Full", cover_url="/test", product_type="personal", price_af_coins=10, published=False)
                if section == "training" else Listing(seller_id=admin.id, listing_type="unique", game_version="car_parking_1", status="paused", brand="Car", model="Test", power_hp=1, max_speed_kph=1, description="Test", price_af_coins=10))
        session.add(item)
    return item


async def publish(sessions, admin, section, item, visible=True):
    async with sessions() as session:
        if section == "training":
            return await set_training_product_state(session, admin, item.id, "publish" if visible else "hide")
        return await set_listing_publication(session, admin, item.id, visible)


@pytest.mark.asyncio
@pytest.mark.parametrize("section", ["unique", "training"])
async def test_two_signed_accounts_baseline_snapshot_hide_republish_and_restart(section):
    async with isolated_pg() as (engine, sessions):
        async with engine.begin() as conn:
            await conn.execute(text("CREATE SEQUENCE content_publication_revision_seq"))
        admin = await signed_login(sessions, 88000)
        admin.role = "admin"
        old = await draft(sessions, admin, section)
        await publish(sessions, admin, section, old)
        a, b = await signed_login(sessions, 88001), await signed_login(sessions, 88002)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client_app(sessions)), base_url="http://test") as client:
            async def unread(user):
                response = await client.get("/api/content/unseen", headers=headers(user))
                assert response.status_code == 200, response.text
                return response.json()[section]["unseen_count"]
            for user in (a, b):
                assert (await client.get("/api/me", headers=headers(user))).status_code == 200
                assert await unread(user) == 0
            new = await draft(sessions, admin, section)
            assert await unread(a) == 0  # Draft is not new public content.
            published = await publish(sessions, admin, section, new)
            revision = published.content_revision
            assert await unread(a) == await unread(b) == 1
            snapshot = await client.get(f"/api/content/{section}/snapshot", headers=headers(a))
            assert snapshot.status_code == 200, snapshot.text
            snapshot = snapshot.json()
            assert {row["id"] for row in snapshot["items"]} == {str(old.id), str(new.id)}
            # Publication during loading must survive acknowledgement of the old snapshot.
            later = await draft(sessions, admin, section)
            await publish(sessions, admin, section, later)
            result = await client.post(f"/api/content/{section}/mark-seen", headers=headers(a), json={"marker": snapshot["marker"]})
            assert result.status_code == 200 and result.json()["unseen_count"] == 1
            assert await unread(b) == 2
            await publish(sessions, admin, section, later, False)
            assert await unread(a) == 0 and await unread(b) == 1
            await publish(sessions, admin, section, new, False)
            assert await unread(b) == 0
            restored = await publish(sessions, admin, section, new)
            assert restored.content_revision == revision
            if section == "training":
                async with sessions() as session:
                    edited = await update_training_product(session, admin, new.id, TrainingProductUpdate(title="Edited", price_af_coins=20))
                    assert edited.content_revision == revision
            assert await unread(b) == 1
            captured = (await client.get(f"/api/content/{section}/snapshot", headers=headers(b))).json()
            await publish(sessions, admin, section, new, False)
            result = await client.post(f"/api/content/{section}/mark-seen", headers=headers(b), json={"marker": captured["marker"]})
            assert result.status_code == 200
            await publish(sessions, admin, section, new)
            assert await unread(b) == 0  # Hidden between SELECT and acknowledgement, then restored.
            # A new HTTP client/device and DB session retain A's seen state.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client_app(sessions)), base_url="http://test") as client:
            result = await client.get("/api/content/unseen", headers=headers(a))
            assert result.json()[section]["unseen_count"] == 0
            result = await client.get("/api/content/unseen", headers=headers(b))
            assert result.json()[section]["unseen_count"] == 0
            assert (await client.get("/api/content/unseen")).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["cancel", "accept", "race"])
async def test_two_accounts_cancel_accept_serialization_and_direct_api(first):
    async with isolated_pg() as (_, sessions):
        buyer, seller, _, deal = await paid_order(sessions)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client_app(sessions)), base_url="http://test") as client:
            async def cancel():
                return await client.post(f"/api/deals/{deal.id}/cancel", headers=headers(buyer))
            async def accept():
                return await client.post(f"/api/deals/{deal.id}/seller-contacted", headers=headers(seller))
            if first == "race":
                responses = await asyncio.gather(cancel(), accept())
            elif first == "cancel":
                responses = [await cancel(), await accept()]
            else:
                responses = [await accept(), await cancel()]
            assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
            async with sessions() as session:
                stored = await session.get(Deal, deal.id)
                wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
                refunded = stored.status == "cancelled"
                assert (wallet.available_balance, wallet.frozen_balance) == ((100, 0) if refunded else (0, 100))
                count = await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "refund"))
                assert count == int(refunded)
                assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "sale_income")) == 0
            for user in (buyer, seller):
                response = await client.post(f"/api/deals/{deal.id}/cancel", headers=headers(user))
                assert response.status_code == 409


@pytest.mark.asyncio
async def test_legacy_accepted_order_no_timestamp_cannot_cancel_or_timeout_and_support_holds_funds():
    async with isolated_pg() as (_, sessions):
        buyer, seller, _, deal = await paid_order(sessions)
        admin = await signed_login(sessions, 88009)
        now = datetime.now(UTC)
        async with sessions() as session, session.begin():
            (await session.get(User, admin.id)).role = "admin"
            stored = await session.get(Deal, deal.id)
            stored.status = "seller_contacted"
            stored.seller_response_deadline = now - timedelta(seconds=1)
        async with sessions() as session:
            with pytest.raises(HTTPException) as error:
                await cancel_deal(session, buyer, deal.id)
            assert error.value.status_code == 409
        async with sessions() as session:
            assert not await auto_cancel_unanswered_deal(session, deal.id, now=now)
        for _ in range(2):
            async with sessions() as session:
                assert not await auto_cancel_undelivered_deal(session, deal.id, now=deal.seller_delivery_deadline + timedelta(seconds=1))
        async with sessions() as session:
            ticket, *_ = await create_deal_support_case(session, buyer, deal.id, "Не получил автомобиль", "/evidence", uuid.uuid4())
            assert ticket.deal_id == deal.id
        async with sessions() as session:
            assert (await session.get(Deal, deal.id)).status == "disputed"
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))).frozen_balance == 100
            assert await session.scalar(select(func.count()).select_from(DealEvent).where(DealEvent.event_type == "accepted_delivery_overdue")) == 1
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "deal_admin_review")) == 1
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 1


@pytest.mark.asyncio
async def test_migration_resets_existing_badges_without_deleting_users():
    async with isolated_pg(tables=False) as (engine, _):
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: apply_revisions(sync, target="0047_analytics_observations"))
            uid = uuid.uuid4()
            await conn.execute(text("INSERT INTO users(id,telegram_id,first_name,role,is_blocked,bot_started,mini_app_last_active_at) VALUES (:id,99901,'Existing','user',false,true,now())"), {"id": uid})
            await conn.execute(text("INSERT INTO training_products(id,admin_id,title,short_description,full_description,cover_url,product_type,price_af_coins,availability,published,pinned,content_revision) VALUES (:id,:u,'Old','Old','Old','/test','personal',10,'available',true,false,7)"), {"id": uuid.uuid4(), "u": uid})
            await conn.run_sync(lambda sync: apply_revisions(sync, target="head", after="0047_analytics_observations"))
            assert await conn.scalar(text("SELECT COUNT(*) FROM users")) == 1
            assert await conn.scalar(text("SELECT last_seen_revision FROM content_seen_states WHERE section='training'")) == 7
            assert await conn.scalar(text("SELECT COUNT(*) FROM content_seen_states")) == 2


@pytest.mark.asyncio
async def test_publication_revisions_serialize_until_commit_and_rollback_is_not_visible():
    from app.content_catalog import next_publication_revision
    async with isolated_pg() as (engine, sessions):
        async with engine.begin() as conn:
            await conn.execute(text("CREATE SEQUENCE content_publication_revision_seq"))
        admin = await signed_login(sessions, 88011)
        admin.role = "admin"
        first, second = await draft(sessions, admin, "training"), await draft(sessions, admin, "training")
        async with sessions() as writer:
            async with writer.begin():
                item = await writer.get(TrainingProduct, first.id)
                item.content_revision = await next_publication_revision(writer)
                revision = item.content_revision
                item.published = True
                await writer.flush()
                started = asyncio.Event()
                async def competing():
                    started.set()
                    return await publish(sessions, admin, "training", second)
                other = asyncio.create_task(competing())
                await started.wait()
                await asyncio.sleep(0.05)
                assert not other.done()  # N+1 cannot commit ahead of N.
                async with sessions() as reader:
                    assert not await reader.scalar(select(TrainingProduct.published).where(TrainingProduct.id == first.id))
            published = await asyncio.wait_for(other, 10)
            assert published.content_revision > revision
        third = await draft(sessions, admin, "training")
        with pytest.raises(RuntimeError):
            async with sessions() as writer, writer.begin():
                item = await writer.get(TrainingProduct, third.id)
                item.content_revision = await next_publication_revision(writer)
                item.published = True
                await writer.flush()
                raise RuntimeError("Publication failed")
        async with sessions() as reader:
            item = await reader.get(TrainingProduct, third.id)
            assert not item.published and item.content_revision is None
