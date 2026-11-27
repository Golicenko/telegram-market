"""Isolated ledger tests; never call Telegram/Fragment or touch production."""
# ruff: noqa: F811 -- imported pytest fixture
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_CEILING
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.config import Settings
from app import gift_withdrawals as service
from app.models import GiftWithdrawalQuote, Notification, SellerVipPlan, SellerVipSubscription, Wallet, WalletTransaction, WithdrawalRequest
from app.services import decide_withdrawal
from test_manual_gift_withdrawals import db, GIFTS  # noqa: F401


@pytest.fixture
def enabled(monkeypatch):
    policy = Settings(_env_file=None, fragment_withdrawals_enabled=True)
    monkeypatch.setattr(service, "get_settings", lambda: policy)
    return policy


@pytest.mark.parametrize("stars", [51, 52, 53, 77, 123, 567, 1250])
def test_exact_integer_net_does_not_round_to_gift_denominations(enabled, stars):
    budget = (Decimal(stars) / Decimal(".7")).quantize(Decimal(".01"), rounding=ROUND_CEILING)
    result = service.fragment_payout(budget)
    assert result["payout_method"] == "manual_fragment"
    assert result["payout_stars"] == stars
    assert result["gift_plan"] == []
    assert result["gross_af"] == budget
    assert result["fee_af"] == budget - stars
    assert result["unspent_af"] == 0


def test_feature_defaults_off_and_retains_old_gift_ceiling(monkeypatch):
    policy = Settings(_env_file=None)
    assert policy.fragment_withdrawals_enabled is False
    monkeypatch.setattr(service, "get_settings", lambda: policy)
    assert service.fragment_payout(Decimal("100")) is None
    assert service.calculate_quote(Decimal("100"), GIFTS)["payout_stars"] == 70


def test_external_capability_interval_rejects_instead_of_rounding(enabled):
    enabled.fragment_withdrawal_min_stars = 77
    with pytest.raises(HTTPException) as error:
        service.fragment_payout(Decimal("72.86"))
    assert error.value.detail["code"] == "fragment_quantity_unavailable"
    enabled.fragment_withdrawal_min_stars = 51
    enabled.fragment_withdrawal_max_stars = 76
    with pytest.raises(HTTPException):
        service.fragment_payout(Decimal("110"))


@pytest.mark.asyncio
async def test_under_fifty_uses_live_gift_plan_and_same_fee(enabled, db):
    bridge, user, _ = db
    assert service.fragment_payout(Decimal("71.43")) is None
    assert service.calculate_quote(Decimal("71.43"), GIFTS, payout_ceiling=50)["payout_stars"] == 50
    quote = await service.preview_withdrawal(bridge, user, Decimal("30"))
    assert quote["payout_method"] == "manual_gift"
    assert quote["payout_stars"] == 15
    assert quote["gross_af"] == Decimal("21.43")
    assert quote["fee_af"] == Decimal("6.43")


@pytest.mark.asyncio
async def test_fragment_avoids_gift_catalog_but_requires_real_username(enabled, db, monkeypatch):
    bridge, user, _ = db
    async def forbidden():
        pytest.fail("A manual Fragment quote must not depend on Telegram gift availability")
    monkeypatch.setattr(service, "available_gifts", forbidden)
    with pytest.raises(HTTPException) as error:
        await service.preview_withdrawal(bridge, user, Decimal("75.72"))
    assert error.value.detail["code"] == "fragment_username_required"
    with bridge.session.begin():
        assert bridge.session.scalar(select(func.count()).select_from(GiftWithdrawalQuote)) == 0
        user.username = "Valid_username"
    quote = await service.preview_withdrawal(bridge, user, Decimal("75.72"))
    assert quote["payout_stars"] == 53 and quote["payout_method"] == "manual_fragment"


def add_vip(bridge, user, *, expired=False):
    now = datetime.now(UTC)
    with bridge.session.begin():
        plan = SellerVipPlan(code="month", title="VIP на 30 дней", duration_days=30, price_af=79,
            pins_72h=10, pins_24h=0, car_limit=15, account_limit=10)
        sub = SellerVipSubscription(user_id=user.id, request_id=uuid.uuid4(), plan_code=plan.code,
            title=plan.title, source="admin", status="active", price_paid=0, purchased_af=0, earned_af=0, bonus_af=0,
            starts_at=now - timedelta(days=30), expires_at=now - timedelta(seconds=1) if expired else now + timedelta(days=1),
            pins_72h_total=10, pins_72h_remaining=9, pins_24h_total=0, pins_24h_remaining=0, car_limit=15, account_limit=10)
        bridge.session.add_all([plan, sub])
    return sub


@pytest.mark.asyncio
async def test_fragment_reservation_replay_priority_snapshot_and_manual_completion(enabled, db):
    bridge, user, admin = db
    admin = SimpleNamespace(id=admin.id, role="admin", is_blocked=False)
    with bridge.session.begin():
        user.username = "Valid_username"
    vip = add_vip(bridge, user)
    quote = await service.preview_withdrawal(bridge, user, Decimal("75.72"))
    quote_id = uuid.UUID(quote["quote_id"])
    enabled.fragment_withdrawals_enabled = False
    with pytest.raises(HTTPException):
        await service.reserve_gift_withdrawal(bridge, user, quote_id, "")
    with bridge.session.begin():
        assert bridge.session.scalar(select(Wallet)).earned_balance == 100
    enabled.fragment_withdrawals_enabled = True
    request = await service.reserve_gift_withdrawal(bridge, user, quote_id, "")
    request_id = request.id
    assert request.vip_priority is True
    assert request.vip_snapshot["subscription_id"] == str(vip.id)
    assert request.payout_method == "manual_fragment" and request.payout_stars == 53
    with bridge.session.begin():
        vip.status = "expired"
        notice = bridge.session.scalar(select(Notification))
        assert "VIP-ПОЛЬЗОВАТЕЛЬ" in notice.body and "Способ выплаты: Fragment" in notice.body
        assert "Комиссия: 22.72 AF" in notice.body and "К отправке: 53 ⭐" in notice.body
        assert bridge.session.scalar(select(Wallet)).earned_balance == Decimal("24.28")
    # Disabling new Fragment reservations must not strand an existing one.
    enabled.fragment_withdrawals_enabled = False
    replay = await service.reserve_gift_withdrawal(bridge, user, quote_id, "retry")
    assert replay.id == request_id and replay.vip_priority
    await decide_withdrawal(bridge, admin, request_id, "approve", None)
    with pytest.raises(HTTPException) as error:
        await decide_withdrawal(bridge, admin, request_id, "paid", None)
    assert error.value.status_code == 422
    for _ in range(2):
        result = await decide_withdrawal(bridge, admin, request_id, "paid", None, "fragment-receipt-test")
        assert result.status == "paid" and result.vip_priority
    with bridge.session.begin():
        wallet = bridge.session.scalar(select(Wallet))
        assert wallet.earned_balance == Decimal("24.28") and wallet.earned_frozen_balance == 0
        assert wallet.purchased_balance == 500
        assert bridge.session.scalar(select(func.count()).select_from(WithdrawalRequest)) == 1
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "withdrawal_paid")) == 1


@pytest.mark.asyncio
async def test_expired_vip_does_not_mark_new_withdrawal(db):
    bridge, user, _ = db
    add_vip(bridge, user, expired=True)
    quote = await service.preview_withdrawal(bridge, user, Decimal(30))
    request = await service.reserve_gift_withdrawal(bridge, user, uuid.UUID(quote["quote_id"]), "")
    assert request.vip_priority is False and request.vip_snapshot == {}
