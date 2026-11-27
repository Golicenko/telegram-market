"""Actual SQLite persistence/rollback. PostgreSQL races are tested separately."""

# ruff: noqa: F811 -- imported fixture is deliberately re-exported to pytest.
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.schema import CreateIndex, CreateTable

from app import seller_vip as vip
from app.models import (
    AdminAction, Listing, Notification, SellerVipAdminCommand, SellerVipPinUsage,
    SellerVipPlan, SellerVipSubscription, Wallet, WalletTransaction,
)
from test_chat_lifecycle_db import db as db


def plans():
    return [SellerVipPlan(code="month", title="VIP на 30 дней", duration_days=30,
                          price_af=79, pins_72h=10, pins_24h=0, car_limit=15, account_limit=10, enabled=True),
            SellerVipPlan(code="quarter", title="VIP на 3 месяца", duration_days=90,
                          price_af=249, pins_72h=45, pins_24h=23, car_limit=68, account_limit=45, enabled=True)]


@pytest.fixture
def vip_db(db):
    bridge, buyer, seller, listing = db
    bridge.bind = bridge.session.bind
    with bridge.session.bind.begin() as connection:
        for model in (SellerVipPlan, SellerVipSubscription, SellerVipPinUsage, SellerVipAdminCommand, AdminAction):
            connection.execute(CreateTable(model.__table__, if_not_exists=True))
            for index in model.__table__.indexes:
                connection.execute(CreateIndex(index, if_not_exists=True))
    with bridge.session.begin():
        bridge.session.add_all(plans())
    return bridge, buyer, seller, listing


def start(code="month", request_id=None, funding=(79, 0, 0)):
    plan = next(plan for plan in plans() if plan.code == code)
    return vip.Purchase(plan_code=code, request_id=request_id or uuid.uuid4(), quote_fingerprint=vip.confirmation_fingerprint(plan, funding))


@pytest.mark.asyncio
@pytest.mark.parametrize("bonus,purchased,earned,expected", [
    (0, 100, 0, (79, 0, 0)), (100, 0, 0, (0, 0, 79)), (50, 10, 50, (10, 19, 50)),
])
async def test_purchase_regular_bonus_mixed_bonus_first_atomic_ledger_and_no_withdrawable_credit(vip_db, bonus, purchased, earned, expected):
    bridge, buyer, _, _ = vip_db
    with bridge.session.begin():
        wallet = bridge.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
        wallet.bonus_balance, wallet.purchased_balance, wallet.earned_balance = map(Decimal, (bonus, purchased, earned))
    payload = start(funding=expected)
    buyer_id = buyer.id
    subscription, replayed = await vip.purchase(bridge, buyer_id, payload)
    assert not replayed and subscription.status == "active"
    assert (subscription.purchased_af, subscription.earned_af, subscription.bonus_af) == expected
    assert vip.utc(subscription.expires_at) - vip.utc(subscription.starts_at) == timedelta(days=30)
    with bridge.session.begin():
        wallet = bridge.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
        assert wallet.available_balance == bonus + purchased + earned - 79
        assert wallet.frozen_balance == 0 and wallet.total_earned == 0
        assert wallet.earned_balance <= earned and wallet.purchased_balance <= purchased
        entry = bridge.session.scalar(select(WalletTransaction))
        assert entry.transaction_type == "seller_vip_purchase" and entry.amount == -79
        assert entry.available_before - entry.available_after == 79
        assert entry.balance_breakdown["funding"] == dict(zip(("purchased", "earned", "bonus"), map(lambda x: f"{x:.2f}", expected)))
    replay, replayed = await vip.purchase(bridge, buyer.id, payload)
    assert replayed and replay.id == subscription.id
    with bridge.session.begin():
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction)) == 1
        assert bridge.session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "seller_vip_purchased")) == 1
    with pytest.raises(HTTPException) as error:
        await vip.purchase(bridge, buyer_id, start())
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        await vip.purchase(bridge, buyer_id, start("quarter", payload.request_id))
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_quote_insufficient_balance_and_server_plan_authority(vip_db):
    bridge, buyer, _, _ = vip_db
    with bridge.session.begin():
        wallet = bridge.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
        wallet.purchased_balance, wallet.bonus_balance = Decimal("10"), Decimal("50")
    with bridge.session.begin():
        quote = await vip.purchase_quote(bridge, buyer.id, "month")
        assert quote["bonus_af"] == 50 and quote["regular_af"] == 10 and quote["missing_af"] == 19
        assert not quote["can_purchase"]
    with pytest.raises(HTTPException) as error:
        await vip.purchase(bridge, buyer.id, start())
    assert error.value.status_code == 402 and error.value.detail["missing_af"] == "19.00"
    with bridge.session.begin():
        assert wallet.available_balance == 60
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction)) == 0
        assert bridge.session.scalar(select(func.count()).select_from(SellerVipSubscription)) == 0
    with pytest.raises(ValidationError):
        vip.Purchase(plan_code="month", request_id=uuid.uuid4(), price_af=1)


@pytest.mark.asyncio
async def test_plan_change_after_confirmation_requires_new_quote_without_debit(vip_db):
    bridge, buyer, _, _ = vip_db
    buyer_id = buyer.id
    request = start()
    with bridge.session.begin():
        (bridge.session.get(SellerVipPlan, "month")).price_af = 80
    with pytest.raises(HTTPException) as error:
        await vip.purchase(bridge, buyer_id, request)
    assert error.value.status_code == 409 and error.value.detail["code"] == "seller_vip_quote_changed"
    with bridge.session.begin():
        wallet = bridge.session.scalar(select(Wallet).where(Wallet.user_id == buyer_id))
        assert wallet.available_balance == 200 and wallet.frozen_balance == 0
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction)) == 0
        assert bridge.session.scalar(select(func.count()).select_from(SellerVipSubscription)) == 0
        quote = await vip.purchase_quote(bridge, buyer_id, "month")
        assert quote["quote_fingerprint"] != request.quote_fingerprint
    _, replayed = await vip.purchase(bridge, buyer_id, request.model_copy(update={"quote_fingerprint": quote["quote_fingerprint"]}))
    assert not replayed


@pytest.mark.asyncio
async def test_funding_change_never_silently_replaces_confirmed_bonus_with_regular_af(vip_db):
    bridge, buyer, _, _ = vip_db
    buyer_id = buyer.id
    with bridge.session.begin():
        wallet = bridge.session.scalar(select(Wallet).where(Wallet.user_id == buyer_id))
        wallet.bonus_balance = Decimal(50)
        quote = await vip.purchase_quote(bridge, buyer_id, "month")
        assert quote["bonus_af"] == 50 and quote["regular_af"] == 29
        wallet.bonus_balance = 0  # A different authorized action used the bonus.
    payload = vip.Purchase(plan_code="month", request_id=uuid.uuid4(), quote_fingerprint=quote["quote_fingerprint"])
    with pytest.raises(HTTPException) as error:
        await vip.purchase(bridge, buyer_id, payload)
    assert error.value.status_code == 409 and error.value.detail["code"] == "seller_vip_quote_changed"
    with bridge.session.begin():
        assert bridge.session.scalar(select(Wallet).where(Wallet.user_id == buyer_id)).purchased_balance == 200
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction)) == 0
        assert bridge.session.scalar(select(func.count()).select_from(SellerVipSubscription)) == 0


@pytest.mark.asyncio
async def test_pin_preserves_money_idempotent_and_second_pin_does_not_consume(vip_db):
    bridge, _, seller, listing = vip_db
    subscription, _ = await vip.purchase(bridge, seller.id, start())
    payload = vip.PinRequest(listing_id=listing.id, duration_hours=72, request_id=uuid.uuid4())
    usage, replayed = await vip.pin(bridge, seller.id, payload)
    assert not replayed and subscription.pins_72h_remaining == 9 and listing.pinned
    assert abs((vip.utc(usage.pinned_until) - vip.now_utc()).total_seconds() - 72 * 3600) < 5
    repeat, replayed = await vip.pin(bridge, seller.id, payload)
    assert replayed and repeat.id == usage.id and subscription.pins_72h_remaining == 9
    with pytest.raises(HTTPException) as error:
        await vip.pin(bridge, seller.id, payload.model_copy(update={"request_id": uuid.uuid4()}))
    assert error.value.status_code == 409
    with bridge.session.begin():
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction)) == 1
        assert bridge.session.scalar(select(func.count()).select_from(SellerVipPinUsage)) == 1
        assert bridge.session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "vip_completed")) == 1
        assert bridge.session.scalar(select(Wallet).where(Wallet.user_id == seller.id)).available_balance == 121


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,status,deleted,reserved,hours", [
    ("car", "active", False, False, 24), ("car", "paused", False, False, 72),
    ("car", "sold", False, False, 72), ("car", "active", True, False, 72),
    ("car", "active", False, True, 72), ("account", "active", False, False, 72),
])
async def test_unavailable_pin_leaves_all_allowances_and_funds_unchanged(vip_db, kind, status, deleted, reserved, hours):
    bridge, _, seller, listing = vip_db
    subscription, _ = await vip.purchase(bridge, seller.id, start())
    with bridge.session.begin():
        listing.product_kind, listing.status = kind, status
        if kind == "account":
            listing.power_hp = listing.max_speed_kph = None
        listing.deleted_at = vip.now_utc() if deleted else None
        listing.reserved_by_deal_id = uuid.uuid4() if reserved else None
    with pytest.raises(HTTPException) as error:
        await vip.pin(bridge, seller.id, vip.PinRequest(listing_id=listing.id, duration_hours=hours, request_id=uuid.uuid4()))
    assert error.value.status_code == 409
    with bridge.session.begin():
        row = bridge.session.get(SellerVipSubscription, subscription.id)
        assert row.pins_72h_remaining == 10 and row.pins_24h_remaining == 0
        assert bridge.session.scalar(select(func.count()).select_from(SellerVipPinUsage)) == 0


@pytest.mark.asyncio
async def test_nonowner_pin_forbidden_and_expiry_retains_listing_and_existing_pin(vip_db):
    bridge, buyer, seller, listing = vip_db
    sub, _ = await vip.purchase(bridge, buyer.id, start())
    with pytest.raises(HTTPException) as error:
        await vip.pin(bridge, buyer.id, vip.PinRequest(listing_id=listing.id, duration_hours=72, request_id=uuid.uuid4()))
    assert error.value.status_code == 404
    with bridge.session.begin():
        sub = bridge.session.get(SellerVipSubscription, sub.id)
        sub.starts_at = vip.now_utc() - timedelta(days=30)
        sub.expires_at = vip.now_utc() - timedelta(seconds=1)
        listing.pinned = True
        listing.pinned_until = vip.now_utc() + timedelta(days=2)
    await vip.process_expiries(bridge)
    await vip.process_expiries(bridge)
    with bridge.session.begin():
        assert await vip.active_subscription(bridge, buyer.id) is None
        assert sub.status == "expired" and listing.status == "active" and listing.pinned
        assert bridge.session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "seller_vip_expired")) == 1
        assert bridge.session.scalar(select(func.count()).select_from(Listing)) == 1


@pytest.mark.asyncio
async def test_warning_expiry_once_repurchase_keeps_history_and_new_allowances(vip_db):
    bridge, buyer, _, _ = vip_db
    first, _ = await vip.purchase(bridge, buyer.id, start())
    with bridge.session.begin():
        first.starts_at = vip.now_utc() - timedelta(days=29)
        first.expires_at = vip.now_utc() + timedelta(hours=23)
    await vip.process_expiries(bridge)
    await vip.process_expiries(bridge)
    with bridge.session.begin():
        assert bridge.session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "seller_vip_expiring")) == 1
        first.expires_at = vip.now_utc() - timedelta(seconds=1)
    second, replayed = await vip.purchase(bridge, buyer.id, start())
    assert not replayed and second.id != first.id and second.pins_72h_remaining == 10
    await vip.process_expiries(bridge)
    with bridge.session.begin():
        assert first.status == "expired"
        assert bridge.session.scalar(select(func.count()).select_from(SellerVipSubscription)) == 2
        assert bridge.session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "seller_vip_expired")) == 1
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction)) == 2


@pytest.mark.asyncio
async def test_admin_grant_extend_disable_idempotent_audited_without_financial_mutation(vip_db):
    bridge, buyer, seller, _ = vip_db
    with bridge.session.begin():
        seller.role = "admin"
    command = vip.AdminCommand(user_id=buyer.id, action="grant", plan_code="quarter", reason="Test explicit grant", request_id=uuid.uuid4(), confirmed=True)
    sub, replayed = await vip.apply_admin_command(bridge, seller, command)
    assert not replayed and sub.pins_72h_remaining == 45 and sub.pins_24h_remaining == 23
    assert sub.car_limit == 68 and sub.account_limit == 45 and sub.price_paid == 0
    repeated, replayed = await vip.apply_admin_command(bridge, seller, command)
    assert replayed and repeated.id == sub.id
    old_expiry = vip.utc(sub.expires_at)
    extension = vip.AdminCommand(user_id=buyer.id, action="extend", days=7, reason="Seven extra days", request_id=uuid.uuid4(), confirmed=True)
    await vip.apply_admin_command(bridge, seller, extension)
    await vip.apply_admin_command(bridge, seller, extension)
    assert vip.utc(sub.expires_at) == old_expiry + timedelta(days=7)
    assert sub.pins_72h_remaining == 45 and sub.pins_24h_remaining == 23
    disable = vip.AdminCommand(user_id=buyer.id, action="disable", reason="Owner requested disable", request_id=uuid.uuid4(), confirmed=True)
    await vip.apply_admin_command(bridge, seller, disable)
    assert sub.status == "disabled"
    with bridge.session.begin():
        assert await vip.active_subscription(bridge, buyer.id) is None
        assert bridge.session.scalar(select(func.count()).select_from(AdminAction)) == 3
        assert bridge.session.scalar(select(func.count()).select_from(WalletTransaction)) == 0
        assert bridge.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id)).available_balance == 200
    with pytest.raises(HTTPException) as error:
        await vip.apply_admin_command(bridge, buyer, command)
    assert error.value.status_code == 403
    with pytest.raises(ValidationError):
        vip.AdminCommand(user_id=buyer.id, action="disable", request_id=uuid.uuid4(), reason="abc", confirmed=False)


@pytest.mark.asyncio
async def test_existing_generic_outbox_claims_warning_and_expiry_without_miniapp_activity(vip_db):
    from app.message_notifications import claim_delivery

    bridge, buyer, _, _ = vip_db
    sub, _ = await vip.purchase(bridge, buyer.id, start())
    with bridge.session.begin():
        buyer.bot_started = True
        for notice in bridge.session.scalars(select(Notification)).all():
            notice.delivery_status = "sent"
        sub.starts_at = vip.now_utc() - timedelta(days=29)
        sub.expires_at = vip.now_utc() + timedelta(hours=23)
    await vip.process_expiries(bridge)
    job = await claim_delivery(bridge, buyer.id, vip.now_utc())
    assert job["params"] == {"view": "seller-vip"}
    assert job["notification_type"] == "seller_vip_expiring"
    assert "24 часов" in job["text"]
    with bridge.session.begin():
        bridge.session.get(Notification, job["ids"][0]).delivery_status = "sent"
        sub.expires_at = vip.now_utc() - timedelta(seconds=1)
    await vip.process_expiries(bridge)
    job = await claim_delivery(bridge, buyer.id, vip.now_utc())
    assert job["notification_type"] == "seller_vip_expired" and job["params"] == {"view": "seller-vip"}
    with bridge.session.begin():
        bridge.session.get(Notification, job["ids"][0]).delivery_status = "sent"
    assert await claim_delivery(bridge, buyer.id, vip.now_utc()) is None


@pytest.mark.asyncio
async def test_admin_extension_suppresses_unsent_old_warning_without_allowance_reset(vip_db):
    bridge, buyer, admin, _ = vip_db
    sub, _ = await vip.purchase(bridge, buyer.id, start())
    with bridge.session.begin():
        admin.role = "admin"
        sub.starts_at = vip.now_utc() - timedelta(days=29)
        sub.expires_at = vip.now_utc() + timedelta(hours=23)
        sub.pins_72h_remaining = 4
    await vip.process_expiries(bridge)
    warning_id = sub.warning_notification_id
    command = vip.AdminCommand(user_id=buyer.id, action="extend", days=7, reason="Extend before expiry", request_id=uuid.uuid4(), confirmed=True)
    await vip.apply_admin_command(bridge, admin, command)
    with bridge.session.begin():
        warning = bridge.session.get(Notification, warning_id)
        assert warning.delivery_status == "suppressed" and warning.delivery_error == "seller_vip_extended"
        assert sub.warning_notification_id is None and sub.pins_72h_remaining == 4
