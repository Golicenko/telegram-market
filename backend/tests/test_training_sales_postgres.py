import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import training_analytics
from app.config import Settings, get_settings
from app.models import TrainingMaterial, TrainingProduct, TrainingPurchase, User, Wallet
from app.services import (create_training_payment_intent, complete_training_payment_intent,
    process_successful_payment, purchase_training_product, wallet_snapshot, wallet_transaction)
from test_catalog_and_acceptance_postgres import client_app, headers
from test_referral_bonus_postgres import isolated_pg, signed_login


async def setup(sessions, kind="automatic"):
    teacher = await signed_login(sessions, 990001)
    buyer = await signed_login(sessions, 990002)
    async with sessions() as session, session.begin():
        (await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))).purchased_balance = 100
        user = await session.get(User, buyer.id)
        user.username = "example_buyer"
        buyer.username = "example_buyer"
        product = TrainingProduct(admin_id=teacher.id, title="GameGuardian Android", short_description="Short",
            full_description="Full", cover_url="/test.jpg", product_type=kind, price_af_coins=30, published=True)
        session.add(product)
        await session.flush()
        if kind == "automatic":
            session.add(TrainingMaterial(product_id=product.id, title="Guide", material_type="text", delivery_reference="Actual purchased text"))
    return teacher, buyer, product


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["automatic", "personal"])
async def test_real_purchase_retries_search_dates_refunds_and_legacy(kind):
    async with isolated_pg() as (_, sessions):
        teacher, buyer, product = await setup(sessions, kind)
        async def purchase():
            async with sessions() as session:
                return await purchase_training_product(session, buyer, product.id)
        outcomes = await asyncio.gather(purchase(), purchase(), purchase())
        assert sum(created for _, created in outcomes) == 1
        order = outcomes[0][0]
        when = datetime(2026, 10, 13, 22, 15, 23, tzinfo=UTC)  # 00:15:23 Oct 14 Bratislava.
        now = datetime(2026, 10, 14, 12, tzinfo=UTC)
        async with sessions() as session, session.begin():
            (await session.get(TrainingPurchase, order.id)).created_at = when
            # Hide/delete the product: its paid snapshot remains in reports.
            stored = await session.get(TrainingProduct, product.id)
            stored.published, stored.deleted_at, stored.title = False, now, "Edited title"
        async def report(**kwargs):
            async with sessions() as session:
                return await training_analytics.report_data(session, now=now, **kwargs)
        result = await report()
        item = result["items"][0]
        assert item["title"] == "GameGuardian Android" and item["buyer_username"] == "example_buyer"
        assert item["purchased_at"] == when and item["amount_af"] == 30
        assert item["profile_url"] == "https://t.me/example_buyer"
        assert item["number"] == str(order.id) and item["buyer_id"] == buyer.id
        assert item["payment_method"] == "af_balance" and item["payment_status"] == "paid"
        assert result["counts"] == {"today": 1, "week": 1, "month": 1, "all_time": 1}
        assert result["summary"]["gross_af"] == 30 and result["summary"]["unique_buyers"] == 1
        assert (await report(search="GameGuardian"))["total"] == 1
        assert (await report(search="example_buyer"))["total"] == 1
        assert (await report(search=str(buyer.telegram_id)))["total"] == 1
        assert (await report(search=str(order.id)))["total"] == 1
        assert (await report(buyer="Unknown"))["total"] == 0
        assert (await report(start=when.date(), end=when.date()))["total"] == 0
        assert (await report(timezone="UTC", start=when.date(), end=when.date()))["total"] == 1
        # The report reads refund facts, never performs or invents a refund.
        async with sessions() as session, session.begin():
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            session.add(wallet_transaction(wallet, "training_refund", Decimal("30"), *wallet_snapshot(wallet),
                "Isolated refund ledger fixture", training_purchase_id=order.id, external_reference=f"refund:{order.id}"))
            (await session.get(User, buyer.id)).username = None
        result = await report(payment_status="refunded")
        assert result["summary"]["refund_af"] == 30 and result["summary"]["net_af"] == 0
        assert result["items"][0]["buyer_username"] is None
        assert result["items"][0]["profile_url"] == f"tg://user?id={buyer.telegram_id}"
        assert result["counts"]["all_time"] == 1  # Refunded sale is retained.
        stranger = await signed_login(sessions, 990003)
        async with sessions() as session, session.begin():
            legacy = TrainingPurchase(product_id=product.id, buyer_id=stranger.id, seller_id=teacher.id,
                buyer_telegram_id=stranger.telegram_id, buyer_display_name="Legacy", product_type=kind,
                title_snapshot="Legacy snapshot", cover_url_snapshot="/test", price_af_coins=10, seller_payout=7,
                platform_commission=3, status="completed", payment_status="paid", created_at=when)
            session.add(legacy)
        report_all = await report(all_time=True)
        assert report_all["total"] == 2 and report_all["summary"]["paid_count"] == 1
        assert report_all["summary"]["unverified_count"] == 1


@pytest.mark.asyncio
async def test_training_stars_webhook_replay_and_failed_payment_do_not_duplicate_sales():
    async with isolated_pg() as (_, sessions):
        _, buyer, product = await setup(sessions)
        async def factory(*_args):
            return "https://t.me/$isolated-test"
        async with sessions() as session:
            intent = await create_training_payment_intent(session, buyer, product.id, factory)
        async with sessions() as session:
            before = await training_analytics.report_data(session, all_time=True)
            assert before["summary"]["paid_count"] == 0
        payment = {"invoice_payload": intent.invoice_payload, "currency": "XTR", "total_amount": 30,
            "telegram_payment_charge_id": str(uuid.uuid4())}
        async with sessions() as session:
            with pytest.raises(HTTPException):
                await process_successful_payment(session, buyer.telegram_id, {**payment, "is_test": True})
        async def pay():
            async with sessions() as session:
                await process_successful_payment(session, buyer.telegram_id, payment)
                return await complete_training_payment_intent(session, buyer, intent.id, payment["telegram_payment_charge_id"])
        await asyncio.gather(pay(), pay(), pay())
        async with sessions() as session:
            report = await training_analytics.report_data(session, all_time=True)
            assert report["summary"]["paid_count"] == 1 and report["summary"]["gross_af"] == 30
            assert report["items"][0]["payment_method"] == "stars_to_af"
            assert await session.scalar(select(func.count()).select_from(TrainingPurchase)) == 1


@pytest.mark.asyncio
async def test_training_history_authorization_and_invalid_filters():
    async with isolated_pg() as (_, sessions):
        admin, buyer, product = await setup(sessions)
        async with sessions() as session:
            await purchase_training_product(session, buyer, product.id)
        app = client_app(sessions)
        app.include_router(training_analytics.router)
        app.dependency_overrides[get_settings] = lambda: Settings(bot_token="referral-test-token", admin_id=admin.telegram_id, debug=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/admin/training-analytics", headers=headers(buyer))).status_code == 403
            assert (await client.get("/api/admin/training-analytics")).status_code == 401
            result = await client.get("/api/admin/training-analytics?all_time=true", headers=headers(admin))
            assert result.status_code == 200, result.text
            assert result.json()["total"] == 1
            assert "telegram_payment_charge_id" not in result.text and "delivery_reference" not in result.text
            assert (await client.get("/api/admin/training-analytics?timezone=Invalid", headers=headers(admin))).status_code == 422
            assert (await client.get("/api/admin/training-analytics?limit=1000", headers=headers(admin))).status_code == 422


def test_dst_calendar_boundaries():
    from app.admin_operations import date_window
    from datetime import date
    lower, upper = date_window(date(2026, 10, 25), date(2026, 10, 25), "Europe/Bratislava", datetime(2026, 10, 27, tzinfo=UTC))
    assert (upper - lower).total_seconds() == 25 * 3600
