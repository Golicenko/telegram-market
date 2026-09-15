from datetime import UTC, datetime, timedelta
from decimal import Decimal
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from test_chat_lifecycle_db import DB  # SQLite JSONB compiler; persistence, not PG locking.
from app.models import User, Wallet, WalletTransaction, Notification, AdminAction, WithdrawalRequest, GiftWithdrawalQuote
from app.schemas import WithdrawalCreate
from app.gift_withdrawals import calculate_quote, preview_withdrawal, reserve_gift_withdrawal
from app.services import create_withdrawal, decide_withdrawal, cancel_withdrawal

GIFTS = [{"id": str(cost), "star_count": cost} for cost in (15, 25, 50, 100)]


@pytest.mark.parametrize("budget,payout,gross,plan_count", [
    ("30", 15, "21.43", 1), ("35.71", 15, "21.43", 1), ("35.72", 25, "35.72", 1),
    ("42.86", 30, "42.86", 2), ("71.43", 50, "71.43", 1),
    ("142.86", 100, "142.86", 1), ("100", 70, "100.00", 4),
])
def test_exact_combinations_fee_and_unspent(budget, payout, gross, plan_count):
    result = calculate_quote(Decimal(budget), GIFTS)
    assert result["payout_stars"] == payout
    assert result["gross_af"] == Decimal(gross)
    assert result["fee_af"] + payout == result["gross_af"]
    assert result["unspent_af"] == Decimal(budget) - Decimal(gross)
    assert sum(item["quantity"] for item in result["gift_plan"]) == plan_count
    assert sum(item["quantity"] * item["star_count"] for item in result["gift_plan"]) == payout


@pytest.mark.parametrize("budget,gifts", [("0.01", GIFTS), ("21.42", GIFTS), ("100", [])])
def test_impossible_amount_is_error(budget, gifts):
    with pytest.raises(HTTPException) as error:
        calculate_quote(Decimal(budget), gifts)
    assert error.value.status_code == 400


@pytest.fixture
def db(monkeypatch):
    import app.gift_withdrawals as service
    async def catalog(): return GIFTS
    monkeypatch.setattr(service, "available_gifts", catalog)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        for model in (User, Wallet, GiftWithdrawalQuote, WithdrawalRequest, WalletTransaction, Notification, AdminAction):
            connection.execute(CreateTable(model.__table__))
    session = Session(engine, expire_on_commit=False)
    user = User(id=uuid.uuid4(), telegram_id=1, first_name="Buyer", role="user")
    admin = User(id=uuid.uuid4(), telegram_id=2, first_name="Admin", role="admin")
    with session.begin():
        session.add_all([user, admin, Wallet(user_id=user.id, purchased_balance=500, earned_balance=100,
            purchased_frozen_balance=0, earned_frozen_balance=0, total_earned=100, version=0)])
    yield DB(session), user, admin
    session.close(); engine.dispose()


@pytest.mark.asyncio
async def test_reserve_retry_restart_manual_completion_once(db):
    bridge, user, admin = db
    quote = await preview_withdrawal(bridge, user, Decimal(30))
    quote_id = uuid.UUID(quote["quote_id"])
    request = await reserve_gift_withdrawal(bridge, user, quote_id, "Comment")
    first_id = request.id
    second = await reserve_gift_withdrawal(bridge, user, quote_id, "retry")
    assert second.id == first_id and second.status == "pending"
    with bridge.session.begin():
        wallet = bridge.session.scalar(select(Wallet).where(Wallet.user_id == user.id))
        assert wallet.earned_balance == Decimal("78.57")
        assert wallet.earned_frozen_balance == Decimal("21.43")
        assert wallet.purchased_balance == 500
        assert bridge.session.scalar(select(func.count()).select_from(WithdrawalRequest)) == 1
        assert bridge.session.scalar(select(func.count()).select_from(Notification)) == 1
        assert bridge.session.scalar(select(Notification)).delivery_status == "pending"
    # New DB session restores the server quote, request and gift plan.
    old = bridge.session
    bridge.session = Session(old.get_bind(), expire_on_commit=False)
    old.close()
    result = await reserve_gift_withdrawal(bridge, user, quote_id, "restart retry")
    assert result.gift_plan == [{"gift_id": "15", "star_count": 15, "quantity": 1}]
    await decide_withdrawal(bridge, admin, first_id, "approve", None)
    await decide_withdrawal(bridge, admin, first_id, "paid", None)
    await decide_withdrawal(bridge, admin, first_id, "paid", None)
    with bridge.session.begin():
        wallet = bridge.session.scalar(select(Wallet))
        assert wallet.earned_frozen_balance == 0 and wallet.earned_balance == Decimal("78.57")
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "withdrawal_paid")) == 1
        assert bridge.session.scalar(select(func.count()).select_from(AdminAction)) == 2
    bridge.session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_full_reserve_restored_on_rejection_or_user_cancel(db, cancel):
    bridge, user, admin = db
    quote = await preview_withdrawal(bridge, user, Decimal(30))
    request = await reserve_gift_withdrawal(bridge, user, uuid.UUID(quote["quote_id"]), "")
    if cancel:
        await cancel_withdrawal(bridge, user, request.id)
    else:
        await decide_withdrawal(bridge, admin, request.id, "reject", "Cannot deliver")
        await decide_withdrawal(bridge, admin, request.id, "reject", "retry")
    with bridge.session.begin():
        wallet = bridge.session.scalar(select(Wallet))
        assert wallet.earned_balance == 100 and wallet.earned_frozen_balance == 0
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction)) == 2


@pytest.mark.asyncio
async def test_forged_legacy_amount_cannot_bypass_quote(db):
    bridge, user, _ = db
    with pytest.raises(HTTPException) as error:
        await create_withdrawal(bridge, user, WithdrawalCreate(amount=1, payout_method="manual", details="fake"))
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_bought_balance_cannot_be_withdrawn(db):
    bridge, user, _ = db
    with bridge.session.begin():
        bridge.session.scalar(select(Wallet)).earned_balance = 0
    with pytest.raises(HTTPException) as error:
        await preview_withdrawal(bridge, user, Decimal(30))
    assert error.value.status_code == 402


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["expired", "catalog", "balance", "outsider"])
async def test_invalid_quote_cannot_reserve(db, monkeypatch, problem):
    bridge, user, admin = db
    quote = await preview_withdrawal(bridge, user, Decimal(30))
    quote_id = uuid.UUID(quote["quote_id"])
    with bridge.session.begin():
        if problem == "expired": bridge.session.get(GiftWithdrawalQuote, quote_id).expires_at = datetime.now(UTC) - timedelta(seconds=1)
        if problem == "balance": bridge.session.scalar(select(Wallet)).earned_balance = 1
    if problem == "catalog":
        async def changed(): return [{"id": "15", "star_count": 25}]
        monkeypatch.setattr("app.gift_withdrawals.available_gifts", changed)
    with pytest.raises(HTTPException):
        await reserve_gift_withdrawal(bridge, admin if problem == "outsider" else user, quote_id, "")
    with bridge.session.begin():
        assert bridge.session.scalar(select(func.count()).select_from(WithdrawalRequest)) == 0
        assert bridge.session.scalar(select(Wallet)).earned_frozen_balance == 0


@pytest.mark.asyncio
async def test_non_admin_cannot_complete(db):
    bridge, user, _ = db
    with pytest.raises(HTTPException) as error:
        await decide_withdrawal(bridge, user, uuid.uuid4(), "paid", None)
    assert error.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", [False, True])
async def test_catalog_filter_and_safe_errors(monkeypatch, broken):
    from types import SimpleNamespace
    from app.gift_withdrawals import available_gifts
    import app.gift_withdrawals as service
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(bot_token="test-only-secret"))
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url):
            assert url.endswith("/getAvailableGifts")
            return SimpleNamespace(status_code=200, json=lambda: {"ok": not broken, "result": {"gifts": [
                {"id": "allowed", "star_count": 15}, {"id": "premium", "star_count": 25, "is_premium": True},
                {"id": "limited", "star_count": 15, "remaining_count": 5}, {"id": "zero", "star_count": 0},
            ]}})
    monkeypatch.setattr(service.httpx, "AsyncClient", Client)
    if broken:
        with pytest.raises(HTTPException) as error: await available_gifts()
        assert error.value.status_code == 503 and "test-only-secret" not in error.value.detail
    else:
        assert await available_gifts() == [{"id": "allowed", "star_count": 15}]


def test_sale_policy_migration_retains_historical_or_already_settled_rows(monkeypatch):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    from sqlalchemy import text
    path = Path(__file__).parents[1] / "migrations/versions/0039_car_sale_zero_fee.py"
    spec = importlib.util.spec_from_file_location("sale_migration", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE deals (id INTEGER, status TEXT, seller_payout NUMERIC, platform_commission NUMERIC, price_af_coins NUMERIC, frozen_amount NUMERIC)"))
        connection.execute(text("CREATE TABLE wallet_transactions (related_deal_id INTEGER, transaction_type TEXT)"))
        for key, status, frozen in [(1, "paid", 100), (2, "disputed", 100), (3, "completed", 0), (4, "cancelled", 0), (5, "paid", 10), (6, "paid", 100)]:
            connection.execute(text("INSERT INTO deals VALUES (:id,:status,70,30,100,:frozen)"), {"id": key, "status": status, "frozen": frozen})
        connection.execute(text("INSERT INTO wallet_transactions VALUES (6,'sale_income')"))
        monkeypatch.setattr(migration, "op", SimpleNamespace(execute=lambda sql: connection.execute(text(sql))))
        migration.upgrade(); migration.upgrade()
        values = list(connection.execute(text("SELECT id,seller_payout,platform_commission FROM deals ORDER BY id")))
        assert values == [(1,100,0),(2,100,0),(3,70,30),(4,70,30),(5,70,30),(6,70,30)]
    engine.dispose()
