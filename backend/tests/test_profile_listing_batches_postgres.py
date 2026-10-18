"""Profile catalogue serialization, measured in an isolated PostgreSQL schema.

These tests never send Telegram messages or perform a financial transaction.
"""
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, select

from app.models import Conversation, Deal, Listing, ListingImage, ListingLike
from app.routes import listing_out, profile
from test_referral_bonus_postgres import isolated_pg, signed_login


@contextmanager
def selected_queries(engine):
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


async def catalogue_fixture(sessions, viewer, other, count):
    now = datetime.now(UTC)
    groups = {"active_listings": [], "sold_listings": [], "purchases": []}
    async with sessions() as session, session.begin():
        for group, rows in groups.items():
            for index in range(count):
                created = now - timedelta(minutes=index)
                item = Listing(
                    id=uuid.uuid4(),
                    seller_id=other.id if group == "purchases" else viewer.id,
                    listing_type="unique" if index % 2 else "regular",
                    game_version="car_parking_2" if index % 2 else "car_parking_1",
                    status=("reserved" if index % 2 else "active") if group == "active_listings" else "sold",
                    brand=f"Profile {group}", model=str(index),
                    power_hp=index + 1, max_speed_kph=index + 2,
                    description="Isolated profile catalogue regression",
                    price_af_coins=Decimal("100.25"),
                    views_count=index,
                    pinned=index % 3 != 0,
                    # Both active and expired VIP periods must preserve their
                    # existing display semantics; no expiry write is performed.
                    pinned_until=now + timedelta(hours=2 if index % 3 == 1 else -2),
                    sold_at=created if group != "active_listings" else None,
                    created_at=created,
                )
                session.add(item)
                rows.append(item)
        await session.flush()
        for rows in groups.values():
            for index, item in enumerate(rows):
                # Insert deliberately out of order: the response must still
                # preserve the original photo positions.
                session.add_all([
                    ListingImage(listing_id=item.id, position=1, url=f"/uploads/{item.id}-second.jpg"),
                    ListingImage(listing_id=item.id, position=0, url=f"/uploads/{item.id}-first.jpg"),
                    ListingLike(listing_id=item.id, user_id=other.id),
                ])
                if index % 2:
                    session.add(ListingLike(listing_id=item.id, user_id=viewer.id))
        for index, item in enumerate(groups["purchases"]):
            session.add(Deal(
                listing_id=item.id, buyer_id=viewer.id, seller_id=other.id,
                status="completed", price_af_coins=100.25, frozen_amount=0,
                seller_payout=100.25, platform_commission=0,
                completed_at=now - timedelta(minutes=index),
            ))
        if count:
            first = groups["purchases"][0]
            # A completed order can occur repeatedly for the same listing in
            # historical data. The old profile kept both entries.
            session.add(Deal(
                listing_id=first.id, buyer_id=viewer.id, seller_id=other.id,
                status="completed", price_af_coins=80, frozen_amount=0,
                seller_payout=80, platform_commission=0, completed_at=now,
            ))
            session.add(Conversation(
                listing_id=first.id, buyer_id=viewer.id, seller_id=other.id,
                conversation_type="deal", archived_at=now,
                accepted_price_af_coins=Decimal("80.00"),
            ))
    return groups


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 50, 100, 300, 500])
async def test_profile_listing_batches_keep_payload_and_constant_query_count(count):
    async with isolated_pg() as (engine, sessions):
        viewer = await signed_login(sessions, 782001)
        other = await signed_login(sessions, 782002)
        groups = await catalogue_fixture(sessions, viewer, other, count)

        async with sessions() as session:
            # Capture the exact former lookup order independently. SQL had no
            # ORDER BY for completed purchases, so preserve this backend order.
            purchase_deals = list((await session.scalars(select(Deal).where(
                Deal.buyer_id == viewer.id, Deal.status == "completed"
            ))).all())
            expected_purchases = [item.listing_id for item in purchase_deals]

        async with sessions() as session:
            with selected_queries(engine) as queries:
                result = await profile(viewer, session)

            # 10 fixed profile SELECTs, one ambiguity check and four batched
            # serializer SELECTs per nonempty list. The purchase entity lookup
            # is one of those ten. Legacy ambiguous prices add one query each.
            assert len(queries) == (23 if count else 9), queries
            print(f"profile groups={count}, catalogue_rows={3 * count}, SELECTs={len(queries)}")
            assert [item.id for item in result.active_listings] == [item.id for item in groups["active_listings"]]
            assert [item.id for item in result.sold_listings] == [item.id for item in groups["sold_listings"]]
            assert [item.id for item in result.purchases] == expected_purchases
            assert len(result.purchases) == count + int(bool(count))
            assert result.deal_threads == result.conversations == []
            assert result.wallet_transactions == result.withdrawals == []
            assert result.wallet.available_balance == 0
            assert result.wallet.frozen_balance == 0

            # Compare representative complete payloads against the former
            # serializer, including active/expired VIP, CP1/CP2, photo order,
            # likes and the accepted price. Avoid thousands of baseline queries.
            for group in groups:
                rows = getattr(result, group)
                selected = list(dict.fromkeys([0, 1, 2, len(rows) - 1])) if rows else []
                for index in selected:
                    actual = rows[index]
                    original = await listing_out(session, await session.get(Listing, actual.id), viewer.id)
                    assert actual.model_dump(mode="json") == original.model_dump(mode="json")
                    assert actual.images == [f"/uploads/{actual.id}-first.jpg", f"/uploads/{actual.id}-second.jpg"]
            if count:
                accepted = next(item for item in result.purchases if item.id == groups["purchases"][0].id)
                assert accepted.effective_price_af_coins == Decimal("80.00")


@pytest.mark.asyncio
@pytest.mark.parametrize("prices", [(None, Decimal("80.00")), (Decimal("80.00"), Decimal("70.00"))])
async def test_profile_preserves_legacy_price_when_multiple_conversations_exist(prices):
    """A regular dialog and past offers can share a buyer/listing pair.

    The former serializer used scalar() over all matching rows, including NULL;
    market serialization instead keeps the last non-NULL price. Profile batching
    must not silently adopt that different display contract for legacy records.
    """
    async with isolated_pg() as (engine, sessions):
        viewer = await signed_login(sessions, 783001)
        other = await signed_login(sessions, 783002)
        groups = await catalogue_fixture(sessions, viewer, other, 3)
        item_id = groups["purchases"][0].id
        async with sessions() as session, session.begin():
            first = await session.scalar(select(Conversation).where(
                Conversation.listing_id == item_id, Conversation.buyer_id == viewer.id
            ))
            first.accepted_price_af_coins = prices[0]
            if prices[0] is None:
                first.conversation_type = "dialog"
                first.archived_at = None
            session.add(Conversation(
                listing_id=item_id, buyer_id=viewer.id, seller_id=other.id,
                conversation_type="deal", archived_at=datetime.now(UTC),
                accepted_price_af_coins=prices[1],
            ))

        async with sessions() as session:
            # Capture the exact existing scalar query's chosen row rather than
            # inventing a new ordering for previously unordered historical data.
            original = await listing_out(session, await session.get(Listing, item_id), viewer.id)
            with selected_queries(engine) as queries:
                result = await profile(viewer, session)
            assert len(queries) == 24
            matching = [item for item in result.purchases if item.id == item_id]
            assert len(matching) == 2
            assert all(item.model_dump(mode="json") == original.model_dump(mode="json") for item in matching)
            assert result.wallet.available_balance == result.wallet.frozen_balance == 0
