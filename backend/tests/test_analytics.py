import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, text

from app import analytics
from app.analytics import Observation, record_observation, report_data, prune_observations
from app.auth import get_current_user
from app.database import get_session
from app.models import AnalyticsEvent, AnalyticsState, StarPaymentIntent, TrainingProduct, Wallet
from app.services import process_successful_payment, purchase_training_product
from test_referral_bonus_postgres import isolated_pg, signed_login, apply_revisions


def observation(event="miniapp_opened", **values):
    return Observation(event_name=event, event_id=uuid.uuid4(), session_id=uuid.uuid4(), **values)


@pytest.mark.parametrize("event", ["topup_success", "order_paid", "withdrawal_paid", "referral_milestone_paid"])
def test_cannot_spoof_financial_events(event):
    with pytest.raises(ValidationError):
        observation(event)


def test_no_free_text_payload_and_product_scope():
    with pytest.raises(ValidationError):
        observation("miniapp_opened", body="Private message")
    with pytest.raises(ValidationError):
        observation("training_product_view")
    with pytest.raises(ValidationError):
        observation("topup_failure", reason="private raw error")


@pytest.mark.asyncio
async def test_parallel_replays_and_semantic_dedup_do_not_change_wallet():
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 8801)
        payload = observation()

        async def send(value):
            async with sessions() as session, session.begin():
                return await record_observation(session, user, value)

        assert sum(await asyncio.gather(*(send(payload) for _ in range(8)))) == 1
        assert not await send(payload.model_copy(update={"event_id": uuid.uuid4()}))
        with pytest.raises(HTTPException) as conflict:
            await send(payload.model_copy(update={"event_name": "market_viewed"}))
        assert conflict.value.status_code == 409
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(AnalyticsEvent)) == 1
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == user.id))).available_balance == 0


@pytest.mark.asyncio
async def test_report_uses_real_payment_and_training_records_and_matching_cohorts():
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 8802)
        admin = await signed_login(sessions, 8803)
        now = datetime.now(UTC)
        async with sessions() as session, session.begin():
            session.add(AnalyticsState(id=1, started_at=now - timedelta(days=2), retained_from=now - timedelta(days=2)))
            await record_observation(session, user, observation(), now - timedelta(seconds=3))
            await record_observation(session, user, observation("topup_screen_opened"), now - timedelta(seconds=2))
            product = TrainingProduct(admin_id=admin.id, title="Test course", short_description="Test", full_description="Test", cover_url="/test", product_type="personal", price_af_coins=10, published=True)
            session.add(product)
            await session.flush()
            await record_observation(session, user, observation("training_product_view", entity_id=product.id), now - timedelta(seconds=1))
            intent = StarPaymentIntent(user_id=user.id, invoice_payload=f"autoflow_topup:{uuid.uuid4()}", xtr_amount=100, purpose="topup", status="pending", expires_at=now + timedelta(hours=1))
            session.add(intent)
        payment = {"currency": "XTR", "invoice_payload": intent.invoice_payload, "total_amount": 100, "telegram_payment_charge_id": str(uuid.uuid4())}
        for _ in range(2):
            async with sessions() as session:
                await process_successful_payment(session, user.telegram_id, payment)
        for _ in range(2):
            async with sessions() as session:
                await purchase_training_product(session, user, product.id)
        async with sessions() as session:
            data = await report_data(session, (now - timedelta(days=1)).date(), now.date(), "UTC")
            assert data["server_events"]["topup_success"]["count"] == 1
            assert data["server_events"]["topup_success"]["amount"] == 100
            assert data["server_events"]["training_paid"]["count"] == 1
            assert data["funnels"]["topup"] == {"opened_users": 1, "invoice_users": 1, "paid_users": 1}
            assert data["funnels"]["training"] == {"viewed_user_products": 1, "paid_user_products": 1}
            assert data["daily_activity"][0]["dau"] == 1
            assert data["daily_activity"][0]["opens"] == 1
            assert data["seller_accept_seconds"]["median"] is None
            old = await report_data(session, (now - timedelta(days=10)).date(), (now - timedelta(days=9)).date(), "UTC")
            assert old["client_observations"] is None and old["funnels"] is None
        app = FastAPI()
        app.include_router(analytics.router)
        app.dependency_overrides[get_current_user] = lambda: admin
        admin.role = "admin"

        async def database():
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = database
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/admin/analytics/training", params={"start": (now - timedelta(days=1)).date().isoformat(), "end": now.date().isoformat(), "timezone": "UTC"})
            assert response.status_code == 200
            row = response.json()["items"][0]
            assert (row["views"], row["paid"], row["fulfilled"]) == (1, 1, 0)


@pytest.mark.asyncio
async def test_rate_limit_and_retention_only_delete_observations():
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 8804)
        now = datetime.now(UTC)
        async with sessions() as session, session.begin():
            session.add(AnalyticsState(id=1, started_at=now - timedelta(days=300), retained_from=now - timedelta(days=300)))
            await record_observation(session, user, observation(), now - timedelta(days=200))
            for _ in range(120):
                await record_observation(session, user, observation(), now)
        async with sessions() as session, session.begin():
            with pytest.raises(HTTPException) as error:
                await record_observation(session, user, observation(), now)
            assert error.value.status_code == 429
        async with sessions() as session, session.begin():
            assert await prune_observations(session, now) == 1
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(AnalyticsEvent)) == 120
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == user.id))).available_balance == 0
            assert (await session.get(AnalyticsState, 1)).retained_from == now - timedelta(days=180)


@pytest.mark.asyncio
async def test_migration_additive_does_not_invent_historical_events():
    async with isolated_pg(tables=False) as (engine, _):
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: apply_revisions(sync, target="0046_seller_order_progress"))
            await conn.execute(text("INSERT INTO users(id,telegram_id,first_name,role,is_blocked,bot_started) VALUES (:id,8805,'Existing','user',false,true)"), {"id": uuid.uuid4()})
            await conn.run_sync(lambda sync: apply_revisions(sync, target="head", after="0046_seller_order_progress"))
            assert await conn.scalar(text("SELECT COUNT(*) FROM users")) == 1
            assert await conn.scalar(text("SELECT COUNT(*) FROM analytics_events")) == 0
            assert await conn.scalar(text("SELECT started_at IS NOT NULL FROM analytics_state WHERE id=1"))
