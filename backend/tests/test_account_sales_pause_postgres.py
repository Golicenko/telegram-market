"""Signed identities and real PostgreSQL rows; no production or Bot API calls."""

# ruff: noqa: F811 -- pytest injects the explicitly imported shared fixture
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app import account_sales, account_video
from app.models import AccountSecret, Deal, Listing, Wallet, WalletTransaction
from app.services import purchase_listing
from test_account_autodelivery import configuration as configuration, payload
from test_account_autodelivery_postgres import media
from test_catalog_and_acceptance_postgres import client_app, headers
from test_referral_bonus_postgres import isolated_pg, signed_login


@pytest.mark.asyncio
@pytest.mark.parametrize("game", ["car_parking_1", "car_parking_2"])
async def test_signed_pause_existing_deal_and_reenable(configuration, game):
    async with isolated_pg() as (_, sessions):
        seller, buyer, other = [
            await signed_login(sessions, number) for number in (91101, 91102, 91103)
        ]
        video, cover = await media(sessions, seller)
        async with sessions() as session:
            paid_item = await account_sales.publish(
                session, seller, payload(video, cover, game_version=game)
            )
            available = await account_sales.publish(
                session, seller, payload(video, cover, game_version=game)
            )
        async with sessions() as session, session.begin():
            wallet = await session.scalar(
                select(Wallet).where(Wallet.user_id == buyer.id)
            )
            wallet.purchased_balance = 200
        async with sessions() as session:
            deal, _, _ = await purchase_listing(session, buyer, paid_item.id)
        configuration.account_sales_enabled = False
        app = client_app(sessions)
        app.include_router(account_video.router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://isolated"
        ) as client:
            assert (
                await client.get("/api/listings?type=regular", headers=headers(buyer))
            ).json() == []
            for path in (
                f"/api/listings/{available.id}/purchase",
                f"/api/listings/{available.id}/purchase-topup-intent",
            ):
                response = await client.post(path, headers=headers(buyer))
                assert response.status_code == 503, response.text
            response = await client.post(
                f"/api/account-products/{available.id}/pin",
                headers=headers(seller),
                json={"request_id": str(uuid.uuid4())},
            )
            assert response.status_code == 503
            assert (
                await client.get(
                    f"/api/listings/{paid_item.id}", headers=headers(other)
                )
            ).status_code == 503
            assert (
                await client.get(
                    f"/api/listings/{paid_item.id}", headers=headers(buyer)
                )
            ).status_code == 200
            revealed = await client.post(
                f"/api/account-deals/{deal.id}/credentials", headers=headers(buyer)
            )
            assert revealed.status_code == 200, revealed.text
            assert "no-store" in revealed.headers["cache-control"]
            async with sessions() as session, session.begin():
                current = await session.get(Deal, deal.id)
                current.transfer_started_at = datetime.now(UTC) - timedelta(seconds=61)
            for _ in range(2):
                response = await client.post(
                    f"/api/account-deals/{deal.id}/confirm",
                    headers=headers(buyer),
                    json={"checked_access": True},
                )
                assert response.status_code == 200, response.text
            configuration.account_sales_enabled = True
            result = await client.get(
                "/api/listings?type=regular&product_kind=account",
                headers=headers(buyer),
            )
            assert result.status_code == 200, result.text
            assert [row["id"] for row in result.json()] == [str(available.id)]
        async with sessions() as session:
            assert (await session.get(Deal, deal.id)).status == "completed"
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WalletTransaction)
                    .where(WalletTransaction.transaction_type == "sale_income")
                )
                == 1
            )
            assert (await session.get(Listing, available.id)).status == "active"
            assert (await session.get(AccountSecret, available.id)).ciphertext
            assert await session.scalar(select(func.count()).select_from(Listing)) == 2
