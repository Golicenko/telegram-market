"""Persistence/security in SQLite; concurrency proof lives in the PG companion."""

import base64
import uuid
from datetime import UTC, datetime, timedelta
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Response
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app import account_crypto, account_sales, account_pins
from app.auth import get_current_user
from app.config import Settings
from app.database import get_session
from app.models import (
    AccountGrant,
    AccountPin,
    AccountSecret,
    AccountVideo,
    Conversation,
    ConversationMessage,
    Deal,
    DealEvent,
    Listing,
    ListingImage,
    Notification,
    PriceOffer,
    StarPayment,
    UploadedImage,
    User,
    Wallet,
    WalletTransaction,
)
from app.services import complete_deal, purchase_listing, set_deal_status
from test_chat_lifecycle_db import DB, sqlite_json  # noqa: F401 -- SQLite compiler registration


class RequestDB(DB):
    @asynccontextmanager
    async def begin(self):
        # A failed simulated HTTP request expires SQLite's identities. Loading
        # their scalar IDs starts a read transaction; a real new request has a
        # fresh session. Discard only that pre-command read transaction here.
        if self.session.in_transaction():
            assert not self.session.new and not self.session.dirty
            self.session.rollback()
        with self.session.begin():
            yield


@pytest.fixture
def configuration(monkeypatch):
    settings = Settings(
        bot_token="",
        account_sales_enabled=True,
        account_secret_keys={"v1": base64.b64encode(b"x" * 32).decode()},
        account_secret_active_key="v1",
    )
    monkeypatch.setattr(account_crypto, "get_settings", lambda: settings)
    monkeypatch.setattr(account_sales, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def account_db(configuration):
    engine = create_engine("sqlite://")
    models = (
        User,
        Wallet,
        AccountVideo,
        Listing,
        ListingImage,
        UploadedImage,
        AccountSecret,
        Conversation,
        Deal,
        AccountGrant,
        ConversationMessage,
        DealEvent,
        PriceOffer,
        WalletTransaction,
        Notification,
        StarPayment,
        AccountPin,
    )
    with engine.begin() as connection:
        for model in models:
            connection.execute(CreateTable(model.__table__))
    session = Session(engine, expire_on_commit=False)
    seller = User(id=uuid.uuid4(), telegram_id=101, first_name="Seller", role="user")
    buyer = User(id=uuid.uuid4(), telegram_id=102, first_name="Buyer", role="user")
    stranger = User(id=uuid.uuid4(), telegram_id=103, first_name="Other", role="user")
    video = AccountVideo(
        id=uuid.uuid4(),
        owner_id=seller.id,
        object_key="test-private-video",
        content_type="video/mp4",
        ready=True,
    )
    cover = UploadedImage(
        id=uuid.uuid4(),
        owner_id=seller.id,
        content_type="image/jpeg",
        data=b"test image",
        size_bytes=10,
    )
    with session.begin():
        session.add_all([seller, buyer, stranger, video, cover])
        for user in (seller, buyer, stranger):
            session.add(
                Wallet(
                    user_id=user.id,
                    purchased_balance=200,
                    earned_balance=0,
                    purchased_frozen_balance=0,
                    earned_frozen_balance=0,
                    bonus_balance=0,
                    bonus_frozen_balance=0,
                    total_earned=0,
                    version=0,
                )
            )
    yield RequestDB(session), seller, buyer, stranger, video, cover
    session.close()
    engine.dispose()


def payload(video, cover, **changes):
    return account_sales.AccountCreate(
        **{
            "client_request_id": uuid.uuid4(),
            "game_version": "car_parking_1",
            "title": "Rare collection",
            "description": "Actual collection with preview",
            "image_url": f"/api/media/{cover.id}",
            "video_asset_id": video.id,
            "login": "private@example.test",
            "password": "test-password-DO-NOT-LOG",
            "price_af_coins": 100,
            "owns_account": True,
            "no_personal_mail_required": True,
            **changes,
        }
    )


def test_context_bound_authenticated_encryption_and_rotation(configuration):
    secret = {"login": "private", "password": "highly private"}
    kid, encoded = account_crypto.seal("listing:A", secret)
    assert b"highly private" not in encoded
    assert account_crypto.unseal("listing:A", kid, encoded) == secret
    for context, data in [
        ("listing:B", encoded),
        ("listing:A", encoded[:-1] + bytes([encoded[-1] ^ 1])),
    ]:
        with pytest.raises(HTTPException):
            account_crypto.unseal(context, kid, data)
    configuration.account_secret_keys["v2"] = base64.b64encode(b"z" * 32).decode()
    configuration.account_secret_active_key = "v2"
    assert account_crypto.unseal("listing:A", kid, encoded) == secret
    assert account_crypto.seal("listing:A", secret)[0] == "v2"


@pytest.mark.asyncio
async def test_three_free_then_each_fifteen_af_and_replay_once(account_db):
    db, seller, _, _, video, cover = account_db
    for index in range(5):
        request = payload(video, cover, title=f"Account number {index}")
        if index >= 3:
            with pytest.raises(HTTPException) as error:
                await account_sales.publish(db, seller, request)
            assert error.value.status_code == 402
            request.publication_fee_confirmed = True
        item = await account_sales.publish(db, seller, request)
        assert (await account_sales.publish(db, seller, request)).id == item.id
    with db.session.begin():
        wallet = db.session.scalar(select(Wallet).where(Wallet.user_id == seller.id))
        assert wallet.available_balance == 170
        assert db.session.scalar(select(func.count()).select_from(Listing)) == 5
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(WalletTransaction)
                .where(WalletTransaction.transaction_type == "account_publication")
            )
            == 2
        )
        assert all(
            b"DO-NOT-LOG" not in secret.ciphertext
            for secret in db.session.scalars(select(AccountSecret))
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("game", ["car_parking_1", "car_parking_2"])
async def test_full_purchase_delivery_authorization_confirmation_and_no_duplicate_payout(
    account_db, game
):
    db, seller, buyer, other, video, cover = account_db
    item = await account_sales.publish(
        db, seller, payload(video, cover, game_version=game)
    )
    deal, _, created = await purchase_listing(db, buyer, item.id)
    assert (
        created
        and deal.product_kind == "account"
        and deal.status == "transfer_in_progress"
    )
    assert not deal.seller_response_deadline and not deal.seller_delivery_deadline
    with db.session.begin():
        messages = list(db.session.scalars(select(ConversationMessage)))
        assert sum(m.account_card_id == deal.id for m in messages) == 1
        assert all(
            "test-password" not in m.body and "private@example" not in m.body
            for m in messages
        )
        buyer_wallet = db.session.scalar(
            select(Wallet).where(Wallet.user_id == buyer.id)
        )
        seller_wallet = db.session.scalar(
            select(Wallet).where(Wallet.user_id == seller.id)
        )
        assert (
            buyer_wallet.available_balance == 100 and buyer_wallet.frozen_balance == 100
        )
        assert seller_wallet.available_balance == 200
    for actor in (seller, other):
        with pytest.raises(HTTPException) as error:
            await account_sales.reveal(deal.id, Response(), actor, db)
        assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        await complete_deal(db, buyer, deal.id, account_confirmation=True)
    with pytest.raises(HTTPException):
        await set_deal_status(db, seller, deal.id, "seller_contacted")
    response = Response()
    values = await account_sales.reveal(deal.id, response, buyer, db)
    assert values == {
        "login": "private@example.test",
        "password": "test-password-DO-NOT-LOG",
    }
    assert "no-store" in response.headers["cache-control"]
    with pytest.raises(HTTPException):
        await complete_deal(
            db, buyer, deal.id
        )  # Legacy route cannot skip account consent.
    with db.session.begin():
        db.session.get(Deal, deal.id).transfer_started_at = datetime.now(
            UTC
        ) - timedelta(seconds=61)
    for _ in range(2):
        result = await complete_deal(db, buyer, deal.id, account_confirmation=True)
        assert result.status == "completed"
    with db.session.begin():
        assert seller_wallet.earned_balance == deal.seller_payout
        assert buyer_wallet.frozen_balance == 0
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(WalletTransaction)
                .where(WalletTransaction.transaction_type == "sale_income")
            )
            == 1
        )
        assert (
            db.session.get(Conversation, deal.conversation_id).archived_at is not None
        )
    assert account_sales.accessible(result)
    assert not account_sales.accessible(result, datetime.now(UTC) + timedelta(days=2))


@pytest.mark.asyncio
async def test_missing_secret_stops_purchase_before_any_debit(account_db):
    db, seller, buyer, _, video, cover = account_db
    item = await account_sales.publish(db, seller, payload(video, cover))
    with db.session.begin():
        db.session.get(AccountSecret, item.id).ciphertext = None
    with pytest.raises(HTTPException):
        await purchase_listing(db, buyer, item.id)
    with db.session.begin():
        wallet = db.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
        assert wallet.available_balance == 200 and wallet.frozen_balance == 0
        assert db.session.scalar(select(func.count()).select_from(Deal)) == 0


@pytest.mark.asyncio
async def test_account_bonus_payment_does_not_create_withdrawable_seller_income(
    account_db,
):
    db, seller, buyer, _, video, cover = account_db
    item = await account_sales.publish(db, seller, payload(video, cover))
    with db.session.begin():
        wallet = db.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
        wallet.purchased_balance, wallet.bonus_balance = 0, 200
    deal, _, _ = await purchase_listing(db, buyer, item.id)
    await account_sales.reveal(deal.id, Response(), buyer, db)
    with db.session.begin():
        db.session.get(Deal, deal.id).transfer_started_at = datetime.now(
            UTC
        ) - timedelta(seconds=61)
    await complete_deal(db, buyer, deal.id, account_confirmation=True)
    with db.session.begin():
        seller_wallet = db.session.scalar(
            select(Wallet).where(Wallet.user_id == seller.id)
        )
        assert seller_wallet.earned_balance == 0
        assert seller_wallet.bonus_balance == deal.seller_payout


@pytest.mark.asyncio
async def test_secret_not_echoed_by_validation_and_feature_disabled(
    account_db, configuration
):
    db, seller, _, _, video, cover = account_db
    app = FastAPI()
    app.include_router(account_pins.router)

    async def database():
        yield db

    app.dependency_overrides[get_session] = database
    app.dependency_overrides[get_current_user] = lambda: seller
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        data = payload(video, cover).model_dump(mode="json")
        data["login"] = "x"
        data["password"] = "do-not-echo"
        result = await client.post("/api/account-products", json=data)
        assert result.status_code == 422 and "do-not-echo" not in result.text
        configuration.account_sales_enabled = False
        data["login"] = "private@example.test"
        result = await client.post("/api/account-products", json=data)
        assert result.status_code == 503 and "do-not-echo" not in result.text
