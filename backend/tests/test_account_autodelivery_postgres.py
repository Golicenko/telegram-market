"""Real row locks, additive migration, private ACL; isolated schemas only."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException, Response
from sqlalchemy import func, select, text

from app import account_pins, account_sales
from app.models import (
    AccountGrant,
    AccountPin,
    AccountVideo,
    Deal,
    Listing,
    Notification,
    StarPayment,
    SupportTicket,
    UploadedImage,
    Wallet,
    WalletTransaction,
)
from app.services import (
    complete_deal,
    create_deal_support_case,
    purchase_listing,
    resolve_dispute,
)
from app.support_media import router as support_router
from test_account_autodelivery import configuration, payload  # noqa: F401,F811 -- pytest fixture
from test_catalog_and_acceptance_postgres import client_app, headers
from test_private_chat_photos import photo
from test_referral_bonus_postgres import apply_revisions, isolated_pg, signed_login

pytestmark = pytest.mark.usefixtures("configuration")


async def media(sessions, seller):
    async with sessions() as session, session.begin():
        video = AccountVideo(
            id=uuid.uuid4(),
            owner_id=seller.id,
            object_key=str(uuid.uuid4()),
            content_type="video/mp4",
            ready=True,
        )
        cover = UploadedImage(
            id=uuid.uuid4(),
            owner_id=seller.id,
            content_type="image/jpeg",
            data=photo(),
            size_bytes=len(photo()),
        )
        session.add_all([video, cover])
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
        wallet.purchased_balance = 200
    return video, cover


@pytest.mark.asyncio
async def test_parallel_quota_replay_rollback_and_independent_car_count():
    async with isolated_pg() as (_, sessions):
        seller = await signed_login(sessions, 5101)
        video, cover = await media(sessions, seller)

        async def publish(request):
            async with sessions() as session:
                return await account_sales.publish(session, seller, request)

        requests = [
            payload(video, cover, title=f"Account {n}", publication_fee_confirmed=True)
            for n in range(5)
        ]
        await asyncio.wait_for(
            asyncio.gather(*(publish(request) for request in requests)), 20
        )
        await asyncio.wait_for(
            asyncio.gather(*(publish(requests[-1]) for _ in range(8))), 20
        )
        async with sessions() as session:
            wallet = await session.scalar(
                select(Wallet).where(Wallet.user_id == seller.id)
            )
            assert wallet.available_balance == 170
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WalletTransaction)
                    .where(WalletTransaction.transaction_type == "account_publication")
                )
                == 2
            )
            from app.publication_quota import active_listing_count

            assert await active_listing_count(session, seller.id) == 0
        async with sessions() as session, session.begin():
            wallet = await session.scalar(
                select(Wallet).where(Wallet.user_id == seller.id)
            )
            wallet.purchased_balance = 0
        with pytest.raises(HTTPException) as error:
            await publish(payload(video, cover, publication_fee_confirmed=True))
        assert error.value.status_code == 402
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Listing)) == 5


@pytest.mark.asyncio
async def test_two_buyers_one_winner_and_duplicate_confirmation():
    async with isolated_pg() as (_, sessions):
        seller = await signed_login(sessions, 5201)
        buyers = [await signed_login(sessions, n) for n in (5202, 5203)]
        video, cover = await media(sessions, seller)
        for buyer in buyers:
            await media(sessions, buyer)
        async with sessions() as session:
            item = await account_sales.publish(session, seller, payload(video, cover))

        async def buy(buyer):
            async with sessions() as session:
                return await purchase_listing(session, buyer, item.id)

        results = await asyncio.wait_for(
            asyncio.gather(*(buy(b) for b in buyers), return_exceptions=True), 20
        )
        assert (
            sum(isinstance(r, HTTPException) and r.status_code == 409 for r in results)
            == 1
        )
        deal = next(r[0] for r in results if isinstance(r, tuple))
        buyer = next(b for b in buyers if b.id == deal.buyer_id)
        async with sessions() as session:
            await account_sales.reveal(deal.id, Response(), buyer, session)
        async with sessions() as session, session.begin():
            (await session.get(Deal, deal.id)).transfer_started_at = datetime.now(
                UTC
            ) - timedelta(seconds=61)

        async def confirm():
            async with sessions() as session:
                return await complete_deal(
                    session, buyer, deal.id, account_confirmation=True
                )

        await asyncio.wait_for(asyncio.gather(*(confirm() for _ in range(8))), 20)
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(AccountGrant))
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WalletTransaction)
                    .where(WalletTransaction.transaction_type == "sale_income")
                )
                == 1
            )


@pytest.mark.asyncio
async def test_dispute_preserves_secret_freezes_payout_then_refund_once(monkeypatch):
    async with isolated_pg() as (_, sessions):
        seller, buyer = (
            await signed_login(sessions, 5301),
            await signed_login(sessions, 5302),
        )
        video, cover = await media(sessions, seller)
        await media(sessions, buyer)
        async with sessions() as session:
            item = await account_sales.publish(session, seller, payload(video, cover))
        async with sessions() as session:
            deal, _, _ = await purchase_listing(session, buyer, item.id)
        async with sessions() as session:
            await create_deal_support_case(
                session, buyer, deal.id, "Неверный логин или пароль", "", uuid.uuid4()
            )
        monkeypatch.setattr(account_sales, "SessionLocal", sessions)
        await account_sales.purge_once()
        async with sessions() as session:
            assert (await session.get(AccountGrant, deal.id)).ciphertext
        async with sessions() as session:
            with pytest.raises(HTTPException):
                await complete_deal(session, buyer, deal.id, account_confirmation=True)
        # Payout remains frozen; complaint alone is never a refund.
        async with sessions() as session:
            wallet = await session.scalar(
                select(Wallet).where(Wallet.user_id == buyer.id)
            )
            assert wallet.frozen_balance == 100
        admin = await signed_login(sessions, 5303)
        admin.role = "admin"
        key = uuid.uuid4()
        for _ in range(2):
            async with sessions() as session:
                await resolve_dispute(
                    session,
                    admin,
                    deal.id,
                    "refund",
                    "Неверные данные подтверждены проверкой",
                    request_id=key,
                )
        async with sessions() as session, session.begin():
            stored = await session.get(Deal, deal.id)
            stored.cancelled_at = datetime.now(UTC) - timedelta(days=2)
        await account_sales.purge_once()
        async with sessions() as session:
            wallet = await session.scalar(
                select(Wallet).where(Wallet.user_id == buyer.id)
            )
            assert wallet.frozen_balance == 0 and wallet.available_balance == 200
            assert not (await session.get(AccountGrant, deal.id)).ciphertext
            assert (await session.get(Listing, item.id)).status == "paused"
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WalletTransaction)
                    .where(WalletTransaction.transaction_type == "dispute_refund")
                )
                == 1
            )


@pytest.mark.asyncio
async def test_account_vip_stars_receipt_once_and_no_af_credit():
    async with isolated_pg() as (_, sessions):
        seller = await signed_login(sessions, 5401)
        video, cover = await media(sessions, seller)
        async with sessions() as session:
            item = await account_sales.publish(session, seller, payload(video, cover))
        async with sessions() as session, session.begin():
            pin = AccountPin(
                id=uuid.uuid4(),
                listing_id=item.id,
                user_id=seller.id,
                request_id=uuid.uuid4(),
            )
            session.add(pin)
        payment = {
            "currency": "XTR",
            "total_amount": 5,
            "invoice_payload": account_pins.PREFIX + str(pin.id),
            "telegram_payment_charge_id": "isolated-charge",
        }

        async def receive():
            async with sessions() as session:
                await account_pins.receive_payment(session, seller.telegram_id, payment)

        before = datetime.now(UTC)
        await asyncio.wait_for(asyncio.gather(*(receive() for _ in range(6))), 20)
        async with sessions() as session:
            item = await session.get(Listing, item.id)
            assert (
                before + timedelta(hours=24)
                <= item.pinned_until
                <= datetime.now(UTC) + timedelta(hours=24)
            )
            assert (
                await session.scalar(select(func.count()).select_from(StarPayment)) == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.notification_type == "vip_completed")
                )
                == 1
            )
            wallet = await session.scalar(
                select(Wallet).where(Wallet.user_id == seller.id)
            )
            assert wallet.available_balance == 200


@pytest.mark.asyncio
async def test_private_support_upload_and_authorized_full_photo():
    async with isolated_pg() as (_, sessions):
        author, stranger = (
            await signed_login(sessions, 5501),
            await signed_login(sessions, 5502),
        )
        buyer = await signed_login(sessions, 5503)
        app = client_app(sessions)
        app.include_router(support_router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await client.post(
                "/api/uploads?purpose=support",
                headers=headers(author),
                files={"file": ("screen.png", photo(), "image/png")},
            )
            assert result.status_code == 201, result.text
            url = result.json()["url"]
            image_id = uuid.UUID(url.rsplit("/", 1)[1])
            async with sessions() as session, session.begin():
                ticket = SupportTicket(
                    author_id=buyer.id,
                    user_id=buyer.id,
                    buyer_id=buyer.id,
                    seller_id=author.id,
                    topic="other",
                    status="open",
                    screenshot_url=url,
                )
                session.add(ticket)
            path = f"/api/support/tickets/{ticket.id}/photo?preview=false"
            assert (await client.get(path, headers=headers(author))).status_code == 200
            assert (await client.get(path, headers=headers(buyer))).status_code == 200
            assert (
                await client.get(path, headers=headers(stranger))
            ).status_code == 404
            assert (await client.get(f"/api/media/{image_id}")).status_code == 404


@pytest.mark.asyncio
async def test_migration_preserves_old_car_and_adds_private_support_flag():
    async with isolated_pg(tables=False) as (engine, _):
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: apply_revisions(sync, target="0054_private_chat_photos")
            )
            owner, item = uuid.uuid4(), uuid.uuid4()
            await connection.execute(
                text(
                    "INSERT INTO users(id,telegram_id,first_name) VALUES (:id,5601,'Historical')"
                ),
                {"id": owner},
            )
            await connection.execute(
                text(
                    "INSERT INTO listings(id,seller_id,listing_type,game_version,brand,model,power_hp,max_speed_kph,description,price_af_coins) VALUES (:id,:u,'regular','car_parking_1','Old','Car',100,200,'Historical',50)"
                ),
                {"id": item, "u": owner},
            )
            await connection.run_sync(
                lambda sync: apply_revisions(
                    sync,
                    after="0054_private_chat_photos",
                    target="0055_account_autodelivery",
                )
            )
            row = (
                await connection.execute(
                    text(
                        "SELECT product_kind,brand,power_hp FROM listings WHERE id=:id"
                    ),
                    {"id": item},
                )
            ).one()
            assert tuple(row) == ("car", "Old", 100)
