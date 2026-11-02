import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app import owner_finance
from app.admin_access import require_owner
from app.auth import get_current_user
from app.config import Settings, get_settings
from app.database import get_session
from app.models import (PublicationDraft, StarPayment, TrainingMaterial, TrainingProduct,
                        User, Wallet, WalletTransaction, WithdrawalRequest)
from app.services import (complete_deal, purchase_training_product, save_deal_delivery_details,
                          set_deal_status, wallet_snapshot, wallet_transaction)
from test_referral_bonus_postgres import isolated_pg, signed_login
from test_seller_orders_postgres import paid_order


@pytest.mark.asyncio
@pytest.mark.parametrize("role,telegram_id,blocked", [("user", 1, False), ("admin", 2, False), ("admin", 1, True)])
async def test_owner_only_not_all_admins(role, telegram_id, blocked):
    app = FastAPI()
    app.include_router(owner_finance.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=role, telegram_id=telegram_id, is_blocked=blocked)
    app.dependency_overrides[get_settings] = lambda: Settings(admin_id=1, bot_token="", debug=False)
    app.dependency_overrides[get_session] = lambda: None  # Forbidden must run before any query.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/api/admin/finance", "/api/admin/finance/referrals"):
            assert (await client.get(path)).status_code == 403


@pytest.mark.asyncio
async def test_missing_owner_configuration_denies_even_admin():
    user = SimpleNamespace(role="admin", telegram_id=1, is_blocked=False)
    with pytest.raises(HTTPException):
        await require_owner(user, Settings(admin_id=None))
    assert await require_owner(user, Settings(admin_id=1)) is user


def test_projection_separates_units_and_never_exposes_charge_payload():
    sql = str(select(owner_finance.operations(uuid.uuid4())).compile(dialect=postgresql.dialect()))
    assert "UNION ALL" in sql and "raw_payload ->>" in sql  # test-payment exclusion, not a selected private payload
    assert "telegram_payment_charge_id AS" not in sql and "raw_payload AS" not in sql
    assert owner_finance.amount(Decimal("100.10")) == "100.10"


@pytest.mark.asyncio
async def test_real_settlements_revenue_units_refunds_and_readonly():
    async with isolated_pg() as (_, sessions):
        buyer, owner, listing, deal = await paid_order(sessions)
        async with sessions() as session:
            await set_deal_status(session, owner, deal.id, "seller_contacted")
        async with sessions() as session:
            await save_deal_delivery_details(session, buyer, deal.id, "TESTID")
        async with sessions() as session:
            await set_deal_status(session, owner, deal.id, "transfer_in_progress")
        async with sessions() as session:
            await complete_deal(session, buyer, deal.id)
        other = await signed_login(sessions, 9750)
        async with sessions() as session, session.begin():
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            wallet.purchased_balance = 300
            products = []
            for seller, price in ((owner, 30), (other, 20)):
                product = TrainingProduct(admin_id=seller.id, title="Actual test purchase", short_description="Short",
                    full_description="Full", cover_url="/fixture.jpg", product_type="automatic", price_af_coins=price, published=True)
                session.add(product)
                await session.flush()
                session.add(TrainingMaterial(product_id=product.id, title="Test material", material_type="text", delivery_reference="Isolated test"))
                products.append(product)
        purchases = []
        for product in products:
            async with sessions() as session:
                purchase, _ = await purchase_training_product(session, buyer, product.id)
                purchases.append(purchase)
        async with sessions() as session, session.begin():
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            vip = wallet_transaction(wallet, "listing_promotion", Decimal("-10"), *wallet_snapshot(wallet), "Fixture final VIP",
                external_reference="isolated-final-vip")
            session.add(vip)
            # One receipt is linked to one published draft. It appears as a cash
            # receipt AND as recognized service revenue, never summed together.
            receipt = StarPayment(user_id=buyer.id, telegram_payment_charge_id="test-publication-charge",
                xtr_amount=5, af_coin_amount=0, status="publication", raw_payload={}, processed_at=datetime.now(UTC))
            topup = StarPayment(user_id=buyer.id, telegram_payment_charge_id="test-topup-charge",
                xtr_amount=100, af_coin_amount=100, status="credited", raw_payload={}, processed_at=datetime.now(UTC))
            test_receipt = StarPayment(user_id=buyer.id, telegram_payment_charge_id="test-excluded-charge",
                xtr_amount=999, af_coin_amount=999, status="credited", raw_payload={"is_test": True}, processed_at=datetime.now(UTC))
            session.add_all([receipt, topup, test_receipt])
            await session.flush()
            session.add(PublicationDraft(user_id=buyer.id, request_id=uuid.uuid4(), payload={}, price_stars=5,
                payment_id=receipt.id, listing_id=listing.id, status="published"))
            withdrawal = WithdrawalRequest(user_id=owner.id, amount=30, fee_af=9, payout_stars=15, payout_method="manual_gift",
                details="Fixture", status="paid", paid_at=datetime.now(UTC))
            session.add(withdrawal)
            await session.flush()
            owner_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == owner.id))
            session.add(wallet_transaction(owner_wallet, "withdrawal_paid", Decimal("-30"), *wallet_snapshot(owner_wallet),
                "Isolated manual completion", withdrawal_id=withdrawal.id))
        async def report(**kwargs):
            async with sessions() as session:
                return await owner_finance.report_data(session, owner.id, all_time=True, **kwargs)
        result = await report(limit=2)
        summary = result["summary"]
        assert summary["turnover_af"] == "150.00"  # car 100 + training 30 + training 20
        assert summary["publication_income_stars"] == "5.00"
        assert summary["stars_received"] == "105.00"  # not 110, not 1104, not income
        assert summary["platform_income_af"] == owner_finance.amount(19 + sum(p.platform_commission for p in purchases))
        assert summary["owner_income_af"] == owner_finance.amount(deal.seller_payout + purchases[0].seller_payout)
        assert summary["recorded_payout_stars"] == "15.00" and summary["net_profit"] is None
        assert len(result["operations"]) == 2 and result["has_more"]
        page2 = await report(limit=2, offset=2)
        assert page2["summary"] == summary
        assert set((x["kind"], x["reference"]) for x in result["operations"]).isdisjoint(
            (x["kind"], x["reference"]) for x in page2["operations"])
        assert all(x["unit"] in ("AF", "Stars") for x in result["sources"])
        async with sessions() as session:
            before = await session.scalar(select(func.count()).select_from(WalletTransaction))
        await report()
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == before
        # Training refund excludes its platform commission, but preserves the
        # original gross sale and separately reports the buyer refund.
        async with sessions() as session, session.begin():
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            session.add(wallet_transaction(wallet, "training_refund", Decimal("30"), *wallet_snapshot(wallet),
                "Isolated refund fact", training_purchase_id=purchases[0].id))
        refunded = await report()
        assert refunded["summary"]["refund_af"] == "30.00"
        assert refunded["summary"]["platform_income_af"] == owner_finance.amount(19 + purchases[1].platform_commission)


@pytest.mark.asyncio
async def test_referrals_qualified_count_not_multiplied_by_reward_rows():
    async with isolated_pg() as (_, sessions):
        referrer = await signed_login(sessions, 9760)
        for n in range(3):
            await signed_login(sessions, 9761+n, referrer.referral_code)
        # Existing account opening this link cannot become a new referral.
        old = await signed_login(sessions, 9770)
        await signed_login(sessions, old.telegram_id, referrer.referral_code)
        async with sessions() as session:
            result = await owner_finance.referral_leaders(session)
        row = result["items"][0]
        assert row["invited"] == row["qualified"] == 3
        assert row["accrued_af"] == row["credited_bonus_af"] == "10.00"
        assert len(result["items"]) <= 10
        async with sessions() as session, session.begin():
            user = await session.get(User, referrer.id)
            user.username = "bad?redirect=elsewhere"
        async with sessions() as session:
            row = (await owner_finance.referral_leaders(session))["items"][0]
        assert row["username"] is None and row["profile_url"] == "tg://user?id=9760" and row["contact_note"]


@pytest.mark.asyncio
async def test_owner_http_reports_use_readonly_snapshot():
    async with isolated_pg() as (_, sessions):
        owner = await signed_login(sessions, 9790)
        owner.role = "admin"
        app = FastAPI()
        app.include_router(owner_finance.router)
        async def database():
            async with sessions() as session:
                yield session
        app.dependency_overrides[get_current_user] = lambda: owner
        app.dependency_overrides[get_session] = database
        app.dependency_overrides[get_settings] = lambda: Settings(admin_id=9790)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for path in ("/api/admin/finance?all_time=true", "/api/admin/finance/referrals"):
                response = await client.get(path)
                assert response.status_code == 200, response.text
                assert "telegram_payment_charge_id" not in response.text and "raw_payload" not in response.text
            assert (await client.get("/api/admin/finance?timezone=Unknown")).status_code == 422
            assert (await client.get("/api/admin/finance?limit=1000")).status_code == 422


def test_timezone_validation_and_dst():
    lower, upper = owner_finance.date_window(date(2026, 10, 25), date(2026, 10, 25), "Europe/Bratislava", datetime(2026, 11, 2, tzinfo=UTC))
    assert (upper-lower).total_seconds() == 25*3600
