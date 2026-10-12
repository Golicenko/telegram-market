"""Regression coverage for the October financial audit (no external payments)."""
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.schema import CreateTable

from app.models import AdminAction, AdminBalanceAdjustment, Notification, Wallet, WalletTransaction
from app.services import adjust_balance, save_deal_delivery_details, set_deal_status, purchase_listing
from test_chat_lifecycle_db import db as shared_db

db = shared_db


def command(user, **changes):
    return SimpleNamespace(**{
        "user_id": user.id, "request_id": uuid.uuid4(),
        "amount": Decimal("10"), "reason": "Audit regression test", **changes,
    })


def prepare(bridge):
    with bridge.session.bind.begin() as conn:
        for model in (AdminAction, AdminBalanceAdjustment):
            conn.execute(CreateTable(model.__table__))


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [Decimal("10"), Decimal("-10")])
async def test_adjustment_retry_changes_money_and_audit_once(db, amount):
    bridge, buyer, admin, _ = db
    prepare(bridge)
    with bridge.session.begin():
        admin.role = "admin"
    payload = command(buyer, amount=amount)
    for _ in range(3):
        await adjust_balance(bridge, admin, payload)
    with bridge.session.begin():
        wallet = bridge.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
        assert wallet.available_balance == 200 + amount
        for model in (AdminBalanceAdjustment, AdminAction, WalletTransaction):
            assert bridge.session.scalar(select(func.count()).select_from(model)) == 1
        event = bridge.session.scalar(select(AdminAction))
        assert Decimal(event.metadata_json["available_before"]) == 200
        assert Decimal(event.metadata_json["available_after"]) == 200 + amount


@pytest.mark.asyncio
async def test_adjustment_key_cannot_change_payload_and_requires_admin(db):
    bridge, buyer, admin, _ = db
    prepare(bridge)
    payload = command(buyer)
    with pytest.raises(HTTPException) as denied:
        await adjust_balance(bridge, buyer, payload)
    assert denied.value.status_code == 403
    with bridge.session.begin():
        admin.role = "admin"
    actor = SimpleNamespace(id=admin.id, role="admin")
    target = SimpleNamespace(id=buyer.id)
    await adjust_balance(bridge, admin, payload)
    for field, value in (("amount", Decimal("11")), ("user_id", actor.id), ("reason", "Different reason")):
        changed = SimpleNamespace(**{**vars(payload), field: value})
        with pytest.raises(HTTPException) as conflict:
            await adjust_balance(bridge, actor, changed)
        assert conflict.value.status_code == 409
    for changes in ({"request_id": None}, {"amount": Decimal("0")}):
        with pytest.raises(HTTPException) as invalid:
            await adjust_balance(bridge, actor, command(target, **changes))
        assert invalid.value.status_code == 422


@pytest.mark.asyncio
async def test_game_id_cannot_change_after_transfer(db):
    bridge, buyer, seller, listing = db
    deal, _, _ = await purchase_listing(bridge, buyer, listing.id)
    await save_deal_delivery_details(bridge, buyer, deal.id, "original-game-id")
    await set_deal_status(bridge, seller, deal.id, "transfer_in_progress")
    with bridge.session.begin():
        notices = bridge.session.scalar(select(func.count()).select_from(Notification))
    with pytest.raises(HTTPException) as conflict:
        await save_deal_delivery_details(bridge, buyer, deal.id, "different-game-id")
    assert conflict.value.status_code == 409
    with bridge.session.begin():
        assert deal.buyer_game_id == "original-game-id"
        assert bridge.session.scalar(select(func.count()).select_from(Notification)) == notices


@pytest.mark.asyncio
async def test_adjustment_http_requires_admin_and_request_identity(db):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.auth import get_current_user
    from app.database import get_session
    from app.routes import router

    bridge, buyer, admin, _ = db
    prepare(bridge)
    with bridge.session.begin():
        admin.role = "admin"
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: bridge
    payload = {"user_id": str(buyer.id), "request_id": str(uuid.uuid4()), "amount": "10", "reason": "Audit regression"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        app.dependency_overrides[get_current_user] = lambda: buyer
        assert (await client.post("/api/admin/balance-adjustments", json=payload)).status_code == 403
        app.dependency_overrides[get_current_user] = lambda: admin
        missing = {k: v for k, v in payload.items() if k != "request_id"}
        assert (await client.post("/api/admin/balance-adjustments", json=missing)).status_code == 422
        for _ in range(2):
            response = await client.post("/api/admin/balance-adjustments", json=payload)
            assert response.status_code == 200, response.text
            assert Decimal(response.json()["available_balance"]) == 210
