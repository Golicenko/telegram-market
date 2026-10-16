"""Real HTTP/row constraints in isolated PostgreSQL; never live Telegram money."""
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.config import Settings, get_settings
from app.models import Deal, Listing, ListingPromotion, SupportTicket, User, Wallet, WalletTransaction
from app.services import create_deal_support_case
from test_catalog_and_acceptance_postgres import client_app, headers
from test_publication_stars_postgres import listing_payload
from test_referral_bonus_postgres import isolated_pg, signed_login
from test_seller_orders_postgres import paid_order


@pytest.mark.asyncio
@pytest.mark.parametrize("game", ["car_parking_1", "car_parking_2"])
async def test_initial_vip_with_full_balance_real_constraints(game):
    async with isolated_pg() as (_, sessions):
        seller = await signed_login(sessions, 81001)
        async with sessions() as session, session.begin():
            (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).purchased_balance = 10
        payload = listing_payload().model_copy(update={"promote_for_24h": True, "game_version": game}).model_dump(mode="json")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client_app(sessions)), base_url="http://test") as client:
            first = await client.post("/api/listings", headers=headers(seller), json=payload)
            assert first.status_code == 201, first.text
            retry = await client.post("/api/listings", headers=headers(seller), json=payload)
            assert retry.status_code == 201 and retry.json()["id"] == first.json()["id"]
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Listing)) == 1
            assert await session.scalar(select(func.count()).select_from(ListingPromotion)) == 1
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "listing_promotion")) == 1
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).available_balance == 5


async def disputed_order(sessions):
    buyer, seller, listing, deal = await paid_order(sessions)
    admin = await signed_login(sessions, 81002)
    async with sessions() as session, session.begin():
        (await session.get(User, admin.id)).role = "admin"
    async with sessions() as session:
        ticket, *_ = await create_deal_support_case(session, buyer, deal.id, "Автомобиль не получен", "/test.jpg", uuid.uuid4())
    return buyer, seller, listing, deal, admin, ticket


@pytest.mark.asyncio
async def test_support_resolution_response_matches_committed_finances():
    async with isolated_pg() as (_, sessions):
        buyer, seller, listing, deal, admin, ticket = await disputed_order(sessions)
        app = client_app(sessions)
        app.dependency_overrides[get_settings] = lambda: Settings(bot_token="referral-test-token", debug=False, admin_id=admin.telegram_id)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
            result = await client.post(f"/api/admin/support/tickets/{ticket.id}/resolve", headers=headers(admin), json={"outcome": "complete", "reason": "Проверено обеими сторонами", "request_id": str(uuid.uuid4())})
        async with sessions() as session:
            committed = (await session.get(Deal, deal.id)).status
            payout = (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).earned_balance
            assert result.status_code == 200, f"HTTP {result.status_code}; committed deal={committed}; seller earned={payout}; {result.text}"
            assert committed == "completed" and payout == 100
            assert result.json()["status"] == "resolved"
            assert (await session.get(SupportTicket, ticket.id)).status == "resolved"
            assert (await session.get(Listing, listing.id)).status == "sold"
