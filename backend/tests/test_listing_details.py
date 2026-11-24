"""Real queries, bounded public projection, no fabricated seller statistics."""

# ruff: noqa: F811 -- imported pytest fixture
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.schema import CreateTable

from app import listing_details
from app.models import Deal, Favorite, Listing, ListingLike, WalletTransaction
from test_chat_lifecycle_db import db as db


@pytest.fixture
def detail_db(db):
    bridge, buyer, seller, listing = db
    with bridge.session.get_bind().begin() as conn:
        for model in (Favorite, ListingLike):
            conn.execute(CreateTable(model.__table__))
    return bridge, buyer, seller, listing


@pytest.mark.asyncio
async def test_real_sales_visible_cars_pagination_and_private_projection(detail_db):
    bridge, buyer, seller, listing = detail_db
    now = datetime.now(UTC)
    with bridge.session.begin():
        seller.first_name, seller.last_name = "Реальное", "Имя"
        seller.photo_url = "/actual-avatar.jpg"
        bridge.session.add(Favorite(user_id=buyer.id, listing_id=listing.id))
        other_ids, other_records = [], []
        for index, status in enumerate(
            ("active", "active", "reserved", "sold", "paused", "deleted")
        ):
            other = Listing(
                id=uuid.uuid4(),
                seller_id=seller.id,
                listing_type="regular",
                game_version="car_parking_1" if index % 2 else "car_parking_2",
                status=status,
                brand=f"Car {index}",
                model="",
                power_hp=100,
                max_speed_kph=200,
                description="Real record",
                price_af_coins=50,
                pinned=index == 0,
                pinned_until=now + timedelta(days=1) if index == 0 else None,
            )
            bridge.session.add(other)
            other_ids.append(other.id)
            other_records.append(other)
        bridge.session.flush()
        for index, status in enumerate(
            ("completed", "completed", "cancelled", "paid", "disputed")
        ):
            bridge.session.add(
                Deal(
                    listing_id=other_ids[min(index, 4)],
                    buyer_id=buyer.id,
                    seller_id=seller.id,
                    status=status,
                    price_af_coins=50,
                    frozen_amount=50,
                    seller_payout=50,
                    platform_commission=0,
                    completed_at=now if status == "completed" else None,
                )
            )
        # Being a buyer in another completed deal does not increase this seller's sales.
        bridge.session.add(
            Deal(
                listing_id=listing.id,
                buyer_id=seller.id,
                seller_id=buyer.id,
                status="completed",
                price_af_coins=50,
                frozen_amount=50,
                seller_payout=50,
                platform_commission=0,
                completed_at=now,
            )
        )
    first = await listing_details.seller_context(listing.id, 1, 0, buyer, bridge)
    assert first.name == "Реальное Имя" and first.photo_url == "/actual-avatar.jpg"
    assert first.completed_sales == 2 and first.saved_by_me
    assert first.other_active_count == 2 and first.has_more
    assert [item.id for item in first.items] == other_ids[:1]
    second = await listing_details.seller_context(listing.id, 1, 1, buyer, bridge)
    assert [item.id for item in second.items] == other_ids[1:2] and not second.has_more
    public = first.model_dump(mode="json")
    for private in ("telegram_id", "username", "wallet", "email", "role", "password"):
        assert private not in public
    assert await bridge.scalar(select(func.count()).select_from(WalletTransaction)) == 0


@pytest.mark.asyncio
async def test_empty_other_cars_and_no_avatar_are_honest(detail_db):
    bridge, buyer, seller, listing = detail_db
    result = await listing_details.seller_context(listing.id, 12, 0, buyer, bridge)
    assert result.completed_sales == result.other_active_count == 0
    assert result.items == [] and not result.has_more and result.photo_url is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["deleted", "account", "missing"])
async def test_unavailable_or_account_context_is_not_exposed(detail_db, kind):
    bridge, buyer, seller, listing = detail_db
    with bridge.session.begin():
        if kind == "deleted":
            listing.status = "deleted"
        elif kind == "account":
            listing.product_kind, listing.power_hp, listing.max_speed_kph = (
                "account",
                None,
                None,
            )
    with pytest.raises(HTTPException) as error:
        await listing_details.seller_context(
            uuid.uuid4() if kind == "missing" else listing.id, 12, 0, buyer, bridge
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_share_link_uses_configured_bot_not_hardcoded_identity(
    detail_db, monkeypatch
):
    bridge, buyer, _, listing = detail_db

    async def bot():
        return "https://t.me/IsolatedMarketBot"

    monkeypatch.setattr(listing_details, "bot_private_chat_link", bot)
    result = await listing_details.share_link(listing.id, buyer, bridge)
    assert (
        result["url"] == f"https://t.me/IsolatedMarketBot?startapp=listing_{listing.id}"
    )
