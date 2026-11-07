import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select, text

from app.chat_media import router
from app.gift_withdrawals import calculate_quote, preview_withdrawal
from app.models import (
    Conversation,
    ConversationMessage,
    Deal,
    Listing,
    Notification,
    PrivateChatImage,
    User,
    Wallet,
    WalletTransaction,
)
from app.services import (
    complete_deal,
    save_deal_delivery_details,
    send_conversation_message,
    set_deal_status,
)
from app.upload_guard import ImageUploadGuard
from test_catalog_and_acceptance_postgres import client_app, headers
from test_referral_bonus_postgres import apply_revisions, isolated_pg, signed_login
from test_seller_orders_postgres import paid_order


def photo(fmt="PNG", size=(64, 48)):
    output = BytesIO()
    image = Image.new("RGB", size, "navy")
    image.save(output, fmt)
    return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
async def test_signed_photo_atomic_replay_private_read_and_text_history(fmt):
    async with isolated_pg() as (_, sessions):
        buyer, seller, _, deal = await paid_order(sessions)
        outsider = await signed_login(sessions, 9891)
        app = client_app(sessions)
        app.include_router(router)
        app.add_middleware(ImageUploadGuard)
        key = uuid.uuid4()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            url = f"/api/conversations/{deal.conversation_id}/photos"

            async def send():
                return await client.post(
                    url,
                    headers=headers(seller),
                    data={
                        "client_message_id": str(key),
                        "deal_id": str(deal.id),
                        "body": "Дополнительный ракурс",
                    },
                    files={
                        "file": (
                            "test." + fmt.lower(),
                            photo(fmt),
                            "image/" + fmt.lower(),
                        )
                    },
                )

            replies = await asyncio.gather(send(), send(), send())
            assert all(r.status_code == 201 for r in replies), [r.text for r in replies]
            message = replies[0].json()
            assert len({r.json()["id"] for r in replies}) == 1
            assert (
                message["message_type"] == "photo"
                and message["body"] == "Дополнительный ракурс"
            )
            path = url + "/" + message["media_id"]
            for suffix in ("?preview=true", "?preview=false"):
                assert (await client.get(path + suffix)).status_code == 401
                assert (
                    await client.get(path + suffix, headers=headers(outsider))
                ).status_code == 404
                response = await client.get(path + suffix, headers=headers(buyer))
                assert (
                    response.status_code == 200
                    and response.headers["cache-control"] == "private, no-store"
                )
                with Image.open(BytesIO(response.content)) as image:
                    assert image.format == "JPEG" and not image.getexif()
            assert (
                await client.get("/api/media/" + message["media_id"])
            ).status_code == 404
            forbidden = await client.post(
                url,
                headers=headers(outsider),
                data={"client_message_id": str(uuid.uuid4()), "deal_id": str(deal.id)},
                files={"file": ("test.png", photo(), "image/png")},
            )
            assert forbidden.status_code == 404
            response = await client.get(
                f"/api/conversations/{deal.conversation_id}/messages?deal_id={deal.id}",
                headers=headers(buyer),
            )
            assert any(row["id"] == message["id"] for row in response.json())
            await client.post(
                f"/api/conversations/{deal.conversation_id}/read?deal_id={deal.id}&through_message_id={message['id']}",
                headers=headers(buyer),
            )
            delta = await client.get(
                f"/api/conversations/{deal.conversation_id}/messages?after={message['id']}&include_receipts=true&deal_id={deal.id}",
                headers=headers(seller),
            )
            assert (
                delta.json() == [] and message["id"] in delta.headers["x-chat-read-ids"]
            )
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(PrivateChatImage))
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.notification_type == "conversation_message")
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WalletTransaction)
                    .where(WalletTransaction.transaction_type == "sale_income")
                )
                == 0
            )
            assert (
                await session.get(Deal, deal.id)
            ).seller_delivery_deadline == deal.seller_delivery_deadline


@pytest.mark.asyncio
async def test_invalid_large_and_closed_chat_photos_do_not_create_messages():
    async with isolated_pg() as (_, sessions):
        buyer, seller, _, deal = await paid_order(sessions)
        app = client_app(sessions)
        app.include_router(router)
        app.add_middleware(ImageUploadGuard)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            url = f"/api/conversations/{deal.conversation_id}/photos"

            async def send(data, name="test.jpg", mime="image/jpeg"):
                return await client.post(
                    url,
                    headers=headers(seller),
                    data={
                        "client_message_id": str(uuid.uuid4()),
                        "deal_id": str(deal.id),
                    },
                    files={"file": (name, data, mime)},
                )

            assert (await send(b"<script>not an image</script>")).status_code == 415
            assert (await send(b"x" * (12 * 1024 * 1024 + 1))).status_code == 413
            assert (
                await send(photo("GIF"), "animation.gif", "image/gif")
            ).status_code == 415
            valid = await send(photo(size=(3000, 2500)), "large.png", "image/png")
            assert valid.status_code == 201, valid.text
            assert (
                max(valid.json()["media_width"], valid.json()["media_height"]) <= 2560
            )
            async with sessions() as session, session.begin():
                (await session.get(Deal, deal.id)).status = "cancelled"
            assert (await send(photo())).status_code == 409
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(PrivateChatImage))
                == 1
            )


@pytest.mark.asyncio
async def test_photo_rate_is_atomic_and_duplicate_retry_not_counted():
    async with isolated_pg() as (_, sessions):
        _, seller, _, deal = await paid_order(sessions)
        payload = {
            "data": photo("JPEG"),
            "preview": photo("JPEG"),
            "width": 64,
            "height": 48,
        }

        async def send(key):
            async with sessions() as session:
                return await send_conversation_message(
                    session,
                    seller,
                    deal.conversation_id,
                    "",
                    key,
                    deal.id,
                    photo=payload,
                )

        for _ in range(9):
            await send(uuid.uuid4())
        results = await asyncio.gather(
            send(uuid.uuid4()), send(uuid.uuid4()), return_exceptions=True
        )
        assert sum(isinstance(r, tuple) for r in results) == 1
        errors = [r for r in results if not isinstance(r, tuple)]
        assert errors[0].status_code == 429
        item = next(r[0] for r in results if isinstance(r, tuple))
        assert not (await send(item.client_message_id))[2]
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(PrivateChatImage))
                == 10
            )


@pytest.mark.asyncio
async def test_photo_migration_preserves_existing_text_and_money():
    async with isolated_pg(tables=False) as (engine, _):
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: apply_revisions(sync, target="0053_feedback_collection")
            )
            uid = uuid.uuid4()
            await connection.execute(
                User.__table__.insert().values(
                    id=uid, telegram_id=9899, first_name="Existing", role="user"
                )
            )
            await connection.execute(
                Wallet.__table__.insert().values(
                    user_id=uid,
                    earned_balance=30,
                    purchased_balance=70,
                    bonus_balance=10,
                )
            )
            other, lid, cid, mid = [uuid.uuid4() for _ in range(4)]
            await connection.execute(
                User.__table__.insert().values(
                    id=other, telegram_id=9898, first_name="Other", role="user"
                )
            )
            await connection.execute(
                Listing.__table__.insert().values(
                    id=lid,
                    seller_id=uid,
                    listing_type="regular",
                    game_version="car_parking_1",
                    brand="Existing",
                    model="Car",
                    power_hp=1,
                    max_speed_kph=1,
                    description="Existing",
                    price_af_coins=1,
                )
            )
            await connection.execute(
                Conversation.__table__.insert().values(
                    id=cid,
                    listing_id=lid,
                    buyer_id=other,
                    seller_id=uid,
                    conversation_type="dialog",
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO conversation_messages(id,conversation_id,sender_id,body,message_type) VALUES (:id,:cid,:uid,'Existing text','text')"
                ),
                {"id": mid, "cid": cid, "uid": uid},
            )
            await connection.run_sync(
                lambda sync: apply_revisions(
                    sync,
                    after="0053_feedback_collection",
                    target="0054_private_chat_photos",
                )
            )
            assert (
                await connection.scalar(
                    select(Wallet.earned_balance).where(Wallet.user_id == uid)
                )
                == 30
            )
            assert (
                await connection.scalar(
                    select(Wallet.purchased_balance).where(Wallet.user_id == uid)
                )
                == 70
            )
            assert (
                await connection.scalar(
                    select(func.count()).select_from(PrivateChatImage)
                )
                == 0
            )
            assert (
                await connection.scalar(
                    select(ConversationMessage.body).where(
                        ConversationMessage.id == mid
                    )
                )
                == "Existing text"
            )
            columns = (
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='conversation_messages'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert {
                "body",
                "client_message_id",
                "media_id",
                "media_width",
                "media_height",
            }.issubset(columns)


@pytest.mark.asyncio
async def test_separate_wallet_totals_sale_once_and_distinct_withdrawal_errors(
    monkeypatch,
):
    async with isolated_pg() as (_, sessions):
        buyer, seller, _, deal = await paid_order(sessions)
        async with sessions() as session, session.begin():
            (
                await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
            ).purchased_balance = 70

        async def unavailable_catalog():
            raise AssertionError(
                "Purchased money must be rejected before contacting Telegram"
            )

        monkeypatch.setattr("app.gift_withdrawals.available_gifts", unavailable_catalog)
        async with sessions() as session:
            with pytest.raises(Exception) as error:
                await preview_withdrawal(session, seller, Decimal(30))
            assert (
                error.value.status_code == 402
                and error.value.detail["code"] == "insufficient_withdrawable_af"
            )
        async with sessions() as session:
            await set_deal_status(session, seller, deal.id, "seller_contacted")
        async with sessions() as session:
            await save_deal_delivery_details(session, buyer, deal.id, "AB12345")
        async with sessions() as session:
            await set_deal_status(session, seller, deal.id, "transfer_in_progress")
        async with sessions() as session, session.begin():
            (await session.get(Deal, deal.id)).transfer_started_at = datetime.now(
                UTC
            ) - timedelta(seconds=61)
        for _ in range(2):
            async with sessions() as session:
                await complete_deal(session, buyer, deal.id)
        async with sessions() as session:
            wallet = await session.scalar(
                select(Wallet).where(Wallet.user_id == seller.id)
            )
            assert (
                wallet.available_balance == 170
                and wallet.earned_balance == 100
                and wallet.purchased_balance == 70
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WalletTransaction)
                    .where(WalletTransaction.transaction_type == "sale_income")
                )
                == 1
            )
        with pytest.raises(Exception) as error:
            calculate_quote(Decimal(1), [{"id": "15", "star_count": 15}])
        assert (
            error.value.status_code == 400
            and error.value.detail["code"] == "below_minimum_gift"
        )
