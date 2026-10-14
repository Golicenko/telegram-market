"""Slots and financial regressions on disposable PostgreSQL schemas only."""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import publications
from app.models import Deal, Listing, Notification, PublicationDraft, StarPayment, User, Wallet
from app.publication_quota import active_listing_count
from app.schemas import ListingUpdate
from app.services import (cancel_deal, complete_deal, create_listing, delete_listing,
                          save_deal_delivery_details, set_deal_status, set_listing_publication, update_listing)
from test_publication_stars_postgres import listing_payload, payment, seed_slots
from test_referral_bonus_postgres import isolated_pg, signed_login
from test_seller_orders_postgres import paid_order


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 4, 5, 10, 16])
async def test_existing_active_rows_shared_games_and_free_edit(count):
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 89001)
        async with sessions() as session, session.begin():
            await seed_slots(session, user, count)
            (await session.get(User, user.id)).publication_count = 100
        async with sessions() as session:
            rules = await publications.rules_out(session, user)
            assert rules["active_count"] == count
            assert rules["payment_required"] is (count >= 5)
        async with sessions() as session:
            if count >= 5:
                with pytest.raises(HTTPException) as exc:
                    await create_listing(session, user, listing_payload(), listing_type="regular")
                assert exc.value.status_code == 402
            else:
                await create_listing(session, user, listing_payload(), listing_type="regular")
        async with sessions() as session:
            rows = (await session.scalars(select(Listing).where(Listing.seller_id == user.id))).all()
            assert len(rows) == count + int(count < 5)
            assert all(row.status == "active" for row in rows)
        async with sessions() as session:
            updated = await update_listing(session, user, rows[0].id, ListingUpdate(description="Бесплатное редактирование"))
            assert updated.description == "Бесплатное редактирование"
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(StarPayment)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["deleted", "sold", "paused"])
async def test_inactive_listing_releases_slot_without_erasing_history(state):
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 89002)
        async with sessions() as session, session.begin():
            await seed_slots(session, user, 5)
        async with sessions() as session, session.begin():
            row = await session.scalar(select(Listing).where(Listing.seller_id == user.id))
            row.status = state
            if state == "deleted":
                row.deleted_at = datetime.now(UTC)
        async with sessions() as session:
            await create_listing(session, user, listing_payload(), listing_type="regular")
        async with sessions() as session:
            assert await active_listing_count(session, user.id) == 5
            assert await session.scalar(select(func.count()).select_from(Listing)) == 6


@pytest.mark.asyncio
async def test_reserved_disputed_slots_and_real_completion_then_cancel_rejected():
    async with isolated_pg() as (_, sessions):
        buyer, seller, listing, deal = await paid_order(sessions)
        async with sessions() as session, session.begin():
            await seed_slots(session, seller, 4)
        async with sessions() as session:
            assert await active_listing_count(session, seller.id) == 5
        async with sessions() as session:
            with pytest.raises(HTTPException):
                await create_listing(session, seller, listing_payload(), listing_type="regular")
        async with sessions() as session:
            await save_deal_delivery_details(session, buyer, deal.id, "AB123456")
        async with sessions() as session:
            await set_deal_status(session, seller, deal.id, "seller_contacted")
        async with sessions() as session:
            await set_deal_status(session, seller, deal.id, "transfer_in_progress")
        async with sessions() as session, session.begin():
            (await session.get(Deal, deal.id)).transfer_started_at = datetime.now(UTC) - timedelta(minutes=2)
        async with sessions() as session:
            await complete_deal(session, buyer, deal.id)
        async with sessions() as session:
            assert await active_listing_count(session, seller.id) == 4
            assert (await session.get(Listing, listing.id)).status == "sold"
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).earned_balance == 100
        async with sessions() as session:
            with pytest.raises(HTTPException) as exc:
                await cancel_deal(session, buyer, deal.id)
            assert exc.value.status_code == 409
        async with sessions() as session:
            await create_listing(session, seller, listing_payload(), listing_type="regular")


@pytest.mark.asyncio
async def test_republication_and_creation_compete_for_same_slot():
    async with isolated_pg() as (_, sessions):
        seller = await signed_login(sessions, 89003)
        async with sessions() as session, session.begin():
            await seed_slots(session, seller, 5)
        async with sessions() as session, session.begin():
            row = await session.scalar(select(Listing).where(Listing.seller_id == seller.id))
            row.status = "paused"
            row_id = row.id
        async def execute(republish):
            async with sessions() as session:
                try:
                    if republish:
                        await set_listing_publication(session, seller, row_id, True)
                    else:
                        await create_listing(session, seller, listing_payload(), listing_type="regular")
                    return 200
                except HTTPException as error:
                    return error.status_code
        assert sorted(await asyncio.gather(execute(True), execute(False))) == [200, 402]
        async with sessions() as session:
            assert await active_listing_count(session, seller.id) == 5


@pytest.mark.asyncio
async def test_saved_unpaid_draft_becomes_free_and_late_charge_is_retained_for_refund():
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 89004)
        async with sessions() as session, session.begin():
            await seed_slots(session, user, 5)
        payload = listing_payload()
        async with sessions() as session:
            draft = await publications.create_draft(payload, user, session)
        async with sessions() as session:
            old = await session.scalar(select(Listing.id).where(Listing.seller_id == user.id))
        async with sessions() as session:
            await delete_listing(session, user, old)
        async with sessions() as session:
            created = await create_listing(session, user, payload, listing_type="regular")
        async with sessions() as session:
            stored = await session.get(PublicationDraft, uuid.UUID(draft["id"]))
            assert stored.status == "published" and stored.listing_id == created.id and stored.payment_id is None
        async with sessions() as session:
            assert (await publications.validate_checkout(session, user.telegram_id, publications.PREFIX + draft["id"], "XTR", 5, "late"))[0] is False
        async with sessions() as session:
            await publications.receive_payment(session, user.telegram_id, payment(draft))
        async with sessions() as session:
            assert (await session.scalar(select(StarPayment))).status == "publication_review"
            assert await active_listing_count(session, user.id) == 5
            assert (await session.get(PublicationDraft, uuid.UUID(draft["id"]))).status == "published"


@pytest.mark.asyncio
async def test_paid_listing_deletion_does_not_refund_original_charge():
    async with isolated_pg() as (_, sessions):
        user = await signed_login(sessions, 89005)
        async with sessions() as session, session.begin():
            await seed_slots(session, user, 5)
        async with sessions() as session:
            draft = await publications.create_draft(listing_payload(), user, session)
        async with sessions() as session:
            draft_id = await publications.receive_payment(session, user.telegram_id, payment(draft))
            await publications.fulfill(session, draft_id)
        async with sessions() as session:
            listing_id = (await session.get(PublicationDraft, draft_id)).listing_id
        async with sessions() as session:
            await delete_listing(session, user, listing_id)
        async with sessions() as session:
            assert (await session.scalar(select(StarPayment))).status == "publication"
            assert (await session.get(PublicationDraft, draft_id)).status == "published"
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "publication_refunded")) == 0
