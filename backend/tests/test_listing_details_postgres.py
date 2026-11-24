"""Signed API, real PostgreSQL, no live notifications or financial operations."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app import listing_details
from app.models import Listing, ListingImage, User, WalletTransaction
from test_catalog_and_acceptance_postgres import client_app, headers
from test_referral_bonus_postgres import isolated_pg, signed_login


@pytest.mark.asyncio
async def test_signed_seller_context_pagination_privacy_favorites_and_account_pause(
    monkeypatch,
):
    async with isolated_pg() as (_, sessions):
        seller, buyer = [
            await signed_login(sessions, number) for number in (99101, 99102)
        ]
        async with sessions() as session, session.begin():
            owner = await session.get(User, seller.id)
            owner.first_name, owner.last_name = "Public", "Seller"
            owner.photo_url = "/actual-avatar.jpg"
            items = []
            for index in range(29):
                item = Listing(
                    id=uuid.uuid4(),
                    seller_id=seller.id,
                    listing_type="regular",
                    status="active",
                    brand=f"Car {index}",
                    model="",
                    power_hp=100,
                    max_speed_kph=200,
                    description="Actual DB record",
                    price_af_coins=25,
                    game_version="car_parking_1" if index % 2 else "car_parking_2",
                    pinned=index == 1,
                    pinned_until=datetime.now(UTC) + timedelta(hours=1)
                    if index == 1
                    else None,
                )
                session.add(item)
                items.append(item)
            await session.flush()
            session.add(
                ListingImage(listing_id=items[1].id, url="/actual-car.jpg", position=0)
            )
            account = Listing(
                id=uuid.uuid4(),
                seller_id=seller.id,
                listing_type="regular",
                product_kind="account",
                status="active",
                brand="Account",
                model="",
                game_version="car_parking_1",
                power_hp=None,
                max_speed_kph=None,
                description="Must remain hidden",
                price_af_coins=25,
            )
            session.add(account)
        app = client_app(sessions)
        app.include_router(listing_details.router)

        async def bot():
            return "https://t.me/IsolatedMarketBot"

        monkeypatch.setattr(listing_details, "bot_private_chat_link", bot)
        url = f"/api/listings/{items[0].id}/seller-context"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://isolated"
        ) as client:
            assert (await client.get(url)).status_code == 401
            assert (
                await client.get(
                    f"/api/listings/{account.id}/seller-context", headers=headers(buyer)
                )
            ).status_code == 404
            result = await client.get(url, headers=headers(buyer))
            assert result.status_code == 200, result.text
            assert "no-store" in result.headers["cache-control"]
            data = result.json()
            assert data["name"] == "Public Seller" and data["completed_sales"] == 0
            assert data["other_active_count"] == 28 and data["has_more"]
            assert len(data["items"]) == 12 and data["items"][0]["id"] == str(
                items[1].id
            )
            assert data["items"][0]["images"] == ["/actual-car.jpg"]
            assert "telegram_id" not in result.text and "password" not in result.text
            assert (
                await client.get(url + "?limit=25", headers=headers(buyer))
            ).status_code == 422
            assert (
                await client.get(url + "?offset=-1", headers=headers(buyer))
            ).status_code == 422
            later = (
                await client.get(url + "?offset=12&limit=24", headers=headers(buyer))
            ).json()
            assert len(later["items"]) == 16 and not later["has_more"]
            assert not {row["id"] for row in later["items"]} & {
                row["id"] for row in data["items"]
            }
            assert (
                await client.post(
                    f"/api/favorites/{items[0].id}", headers=headers(buyer)
                )
            ).status_code == 201
            assert (await client.get(url, headers=headers(buyer))).json()["saved_by_me"]
            share = await client.get(
                f"/api/listings/{items[0].id}/share-link", headers=headers(buyer)
            )
            assert share.json()["url"].endswith(f"?startapp=listing_{items[0].id}")
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(WalletTransaction)
                )
                == 0
            )
