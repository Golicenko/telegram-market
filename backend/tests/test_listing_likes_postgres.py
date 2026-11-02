import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import Favorite, ListingLike, Wallet, WalletTransaction
from app.routes import like_listing, unlike_listing
from test_referral_bonus_postgres import isolated_pg
from test_seller_orders_postgres import paid_order


@pytest.mark.asyncio
async def test_parallel_like_replays_preserve_favorites_and_money():
    async with isolated_pg() as (_, sessions):
        buyer, seller, listing, _ = await paid_order(sessions)
        async with sessions() as session, session.begin():
            session.add(Favorite(user_id=buyer.id, listing_id=listing.id))
        async with sessions() as session:
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            before = (wallet.available_balance, wallet.frozen_balance)
            ledger_count = await session.scalar(select(func.count()).select_from(WalletTransaction))
        async def call(action):
            async with sessions() as session:
                return await action(listing.id, buyer, session)
        likes = await asyncio.gather(*(call(like_listing) for _ in range(20)))
        assert all(item.likes_count == 1 and item.liked_by_me for item in likes)
        async with sessions() as session:
            with pytest.raises(HTTPException) as error:
                await like_listing(listing.id, seller, session)
            assert error.value.status_code == 403
        unlikes = await asyncio.gather(*(call(unlike_listing) for _ in range(20)))
        assert all(item.likes_count == 0 and not item.liked_by_me for item in unlikes)
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(ListingLike)) == 0
            assert await session.scalar(select(func.count()).select_from(Favorite)) == 1
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            assert (wallet.available_balance, wallet.frozen_balance) == before
            assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == ledger_count
