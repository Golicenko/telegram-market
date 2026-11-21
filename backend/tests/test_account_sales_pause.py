"""A reversible pause: no new account commerce, no lost listings/paid deals."""
# ruff: noqa: F811 -- pytest injects the explicitly imported shared fixtures

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.schema import CreateTable

from app import (
    account_pins,
    account_sales,
    account_video,
    content_catalog,
    routes,
    services,
)
from app.auth import get_current_user
from app.database import get_session
from app.models import (
    AccountListing,
    AccountPin,
    AccountSecret,
    AdminAction,
    CartItem,
    Deal,
    Favorite,
    Listing,
    Notification,
    Referral,
    StarPayment,
    StarPaymentIntent,
    Wallet,
    WalletTransaction,
)
from app.schemas import AccountListingCreate, AccountListingUpdate
from test_account_autodelivery import (
    RequestDB,
    account_db as account_db,
    configuration as configuration,
    payload,
)


class PauseDB(RequestDB):
    async def commit(self):
        self.session.commit()

    async def refresh(self, item):
        self.session.refresh(item)


@pytest.fixture
def pause_db(account_db):
    db, *people = account_db
    with db.session.get_bind().begin() as connection:
        for model in (
            AccountListing,
            AdminAction,
            CartItem,
            Favorite,
            Referral,
            StarPaymentIntent,
        ):
            connection.execute(CreateTable(model.__table__))
    return PauseDB(db.session), *people


def test_pause_is_default_and_uses_existing_switch():
    from app.config import Settings

    assert Settings.model_fields["account_sales_enabled"].default is False


@pytest.mark.asyncio
@pytest.mark.parametrize("game", ["car_parking_1", "car_parking_2"])
async def test_paused_api_catalog_direct_links_mutations_and_restore(
    pause_db, configuration, game
):
    db, seller, buyer, _, video, cover = pause_db
    request = payload(video, cover, game_version=game)
    item = await account_sales.publish(db, seller, request)
    item_id = item.id
    with db.session.begin():
        encrypted = db.session.get(AccountSecret, item_id).ciphertext
        car = Listing(
            seller_id=seller.id,
            listing_type="regular",
            product_kind="car",
            status="active",
            game_version=game,
            brand="Car",
            model="CP",
            power_hp=1,
            max_speed_kph=1,
            description="Actual car",
            price_af_coins=20,
        )
        db.session.add(car)
        db.session.flush()
        car_id = car.id
        db.session.add_all(
            [
                Favorite(user_id=buyer.id, listing_id=item_id),
                CartItem(user_id=buyer.id, listing_id=item_id),
            ]
        )
    configuration.account_sales_enabled = False
    actor = [buyer]
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(account_sales.router)

    async def session_dependency():
        try:
            yield db
        finally:
            db.session.rollback()

    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: actor[0]
    body = request.model_dump(mode="json")
    body.update(login="private@example.test", password="test-password-DO-NOT-LOG")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://isolated"
    ) as client:
        assert (await client.get("/api/account-publication-rules")).json()[
            "enabled"
        ] is False
        for query in ("", "&product_kind=account", f"&game_version={game}"):
            response = await client.get("/api/listings?type=regular" + query)
            assert response.status_code == 200, response.text
            assert all(row["product_kind"] == "car" for row in response.json())
        for url in ("/api/accounts", "/api/favorites", "/api/cart"):
            assert (await client.get(url)).json() == []
        for method, url, data in (
            ("GET", f"/api/listings/{item_id}", None),
            ("POST", f"/api/listings/{item_id}/purchase", None),
            ("POST", f"/api/listings/{item_id}/purchase-topup-intent", None),
            ("POST", f"/api/listings/{item_id}/view", None),
            ("POST", f"/api/listings/{item_id}/like", None),
            ("POST", f"/api/cart/items/{item_id}", None),
            ("POST", f"/api/favorites/{item_id}", None),
        ):
            response = await client.request(method, url, json=data)
            assert response.status_code == 503, (url, response.text)
            assert response.json()["detail"]["code"] == "account_sales_disabled"
        actor[0] = seller
        assert (await client.get(f"/api/listings/{item_id}")).status_code == 200
        for method, url, data in (
            ("POST", "/api/account-products", body),
            ("PATCH", f"/api/account-products/{item_id}", body),
            ("DELETE", f"/api/listings/{item_id}", None),
            (
                "POST",
                f"/api/account-products/{item_id}/pin",
                {"request_id": str(uuid.uuid4())},
            ),
            (
                "POST",
                "/api/account-videos",
                {"content_type": "video/mp4", "size_bytes": 100},
            ),
            ("POST", f"/api/account-videos/{video.id}/complete", None),
            ("POST", f"/api/account-videos/{video.id}/retry", None),
        ):
            response = await client.request(method, url, json=data)
            assert response.status_code == 503, (url, response.text)
        with db.session.begin():
            assert db.session.get(Listing, item_id).status == "active"
            assert db.session.get(AccountSecret, item_id).ciphertext == encrypted
            assert db.session.scalar(select(func.count()).select_from(Deal)) == 0
            assert (
                db.session.scalar(select(func.count()).select_from(StarPaymentIntent))
                == 0
            )
            assert (
                db.session.scalar(select(func.count()).select_from(WalletTransaction))
                == 0
            )
            assert db.session.scalar(select(func.count()).select_from(Favorite)) == 1
            assert db.session.scalar(select(func.count()).select_from(CartItem)) == 1
        configuration.account_sales_enabled = True
        actor[0] = buyer
        assert (await client.get(f"/api/listings/{item_id}")).status_code == 200
        restored = (
            await client.get("/api/listings?type=regular&product_kind=account")
        ).json()
        assert [row["id"] for row in restored] == [str(item_id)]
        assert (await client.get("/api/favorites")).json()[0]["id"] == str(item_id)
        assert (await client.get("/api/cart")).json()[0]["id"] == str(item_id)
    # Cars still use the existing purchase command while the feature is paused.
    configuration.account_sales_enabled = False
    deal, _, created = await services.purchase_listing(db, buyer, car_id)
    assert created and deal.product_kind == "car" and deal.status == "paid"
    configuration.account_sales_enabled = True
    deal, _, created = await services.purchase_listing(db, buyer, item_id)
    assert created and deal.product_kind == "account"


@pytest.mark.asyncio
@pytest.mark.parametrize("dispute", [False, True])
async def test_existing_paid_account_deal_keeps_reveal_video_and_safe_completion(
    pause_db, configuration, dispute
):
    db, seller, buyer, other, video, cover = pause_db
    item = await account_sales.publish(db, seller, payload(video, cover))
    deal, _, _ = await services.purchase_listing(db, buyer, item.id)
    with db.session.begin():
        completed_intent = StarPaymentIntent(
            user_id=buyer.id,
            invoice_payload=f"autoflow_topup:{uuid.uuid4()}",
            xtr_amount=25,
            purpose="listing_checkout",
            listing_id=item.id,
            deal_id=deal.id,
            status="paid",
            checkout_status="completed",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        db.session.add(completed_intent)
    configuration.account_sales_enabled = False
    # A replay refers to the already paid deal; never a second debit or grant.
    replay, _, created = await services.purchase_listing(db, buyer, item.id)
    assert replay.id == deal.id and not created
    _, intent_deal, _ = await services.complete_listing_payment_intent(
        db, buyer, completed_intent.id
    )
    assert intent_deal.id == deal.id
    await account_sales.require_listing_access(db, item, buyer)
    await account_video.require_playback(db, video, buyer)
    with pytest.raises(HTTPException):
        await account_video.require_playback(db, video, other)
    db.session.rollback()
    values = await account_sales.reveal(deal.id, Response(), buyer, db)
    assert values["login"] == "private@example.test"
    with db.session.begin():
        db.session.get(Deal, deal.id).transfer_started_at = datetime.now(
            UTC
        ) - timedelta(seconds=61)
    if dispute:
        result = await services.set_deal_status(db, buyer, deal.id, "disputed")
        assert result.status == "disputed"
        with pytest.raises(HTTPException):
            await services.complete_deal(db, buyer, deal.id, account_confirmation=True)
        with db.session.begin():
            assert (
                db.session.scalar(
                    select(Wallet).where(Wallet.user_id == buyer.id)
                ).frozen_balance
                == 100
            )
    else:
        for _ in range(2):
            result = await account_sales.confirm(
                deal.id, account_sales.Receipt(checked_access=True), buyer, db
            )
            assert result.status == "completed"
        with db.session.begin():
            assert (
                db.session.scalar(
                    select(func.count())
                    .select_from(WalletTransaction)
                    .where(WalletTransaction.transaction_type == "sale_income")
                )
                == 1
            )
            assert (
                db.session.scalar(
                    select(Wallet).where(Wallet.user_id == buyer.id)
                ).frozen_balance
                == 0
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["listing_checkout", "cart_checkout", "topup"])
async def test_old_invoice_precheckout_and_confirmed_payment_during_pause(
    pause_db, configuration, purpose
):
    db, seller, buyer, _, video, cover = pause_db
    item = await account_sales.publish(db, seller, payload(video, cover))
    with db.session.begin():
        intent_id = uuid.uuid4()
        intent = StarPaymentIntent(
            id=intent_id,
            user_id=buyer.id,
            invoice_payload=f"autoflow_topup:{intent_id}",
            xtr_amount=25,
            purpose=purpose,
            listing_id=item.id if purpose == "listing_checkout" else None,
            seller_id=seller.id,
            listing_price_af_coins=100,
            checkout_status="pending"
            if purpose == "listing_checkout"
            else "not_requested",
            context={"listing_ids": [str(item.id)]}
            if purpose == "cart_checkout"
            else {},
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        db.session.add(intent)
    configuration.account_sales_enabled = False
    ok, _ = await services.validate_star_pre_checkout(
        db, buyer.telegram_id, intent.invoice_payload, "XTR", 25
    )
    assert ok is (purpose == "topup")
    db.session.rollback()
    payment = {
        "currency": "XTR",
        "total_amount": 25,
        "invoice_payload": intent.invoice_payload,
        "telegram_payment_charge_id": "isolated-pause-charge",
    }
    assert await services.process_successful_payment(db, buyer.telegram_id, payment)
    assert not await services.process_successful_payment(db, buyer.telegram_id, payment)
    if purpose == "listing_checkout":
        for _ in range(2):
            result, deal, _ = await services.complete_listing_payment_intent(
                db, buyer, intent.id
            )
            assert result.checkout_status == "listing_unavailable" and deal is None
        with db.session.begin():
            assert (
                db.session.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(
                        Notification.notification_type == "listing_checkout_unavailable"
                    )
                )
                == 1
            )
    with db.session.begin():
        wallet = db.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
        assert wallet.available_balance == 225 and wallet.frozen_balance == 0
        assert db.session.scalar(select(func.count()).select_from(Deal)) == 0


@pytest.mark.asyncio
async def test_pending_pin_is_not_activated_if_payment_arrives_after_pause(
    pause_db, configuration
):
    db, seller, _, _, video, cover = pause_db
    item = await account_sales.publish(db, seller, payload(video, cover))
    with db.session.begin():
        pin = AccountPin(
            id=uuid.uuid4(),
            listing_id=item.id,
            user_id=seller.id,
            request_id=uuid.uuid4(),
        )
        db.session.add(pin)
    configuration.account_sales_enabled = False
    ok, _ = await account_pins.validate_checkout(
        db, seller.telegram_id, account_pins.PREFIX + str(pin.id), "XTR", 5, "q"
    )
    assert not ok
    payment = {
        "currency": "XTR",
        "total_amount": 5,
        "invoice_payload": account_pins.PREFIX + str(pin.id),
        "telegram_payment_charge_id": "isolated-paused-pin",
    }
    for _ in range(2):
        await account_pins.receive_payment(db, seller.telegram_id, payment)
    with db.session.begin():
        assert db.session.get(AccountPin, pin.id).status == "refund_pending"
        assert not db.session.get(Listing, item.id).pinned
        assert db.session.scalar(select(func.count()).select_from(StarPayment)) == 1
        assert (
            db.session.scalar(
                select(Wallet).where(Wallet.user_id == seller.id)
            ).available_balance
            == 200
        )


@pytest.mark.asyncio
async def test_legacy_admin_and_republication_are_gated_but_read_history_is_kept(
    pause_db, configuration
):
    db, seller, buyer, _, video, cover = pause_db
    item = await account_sales.publish(db, seller, payload(video, cover))
    legacy_payload = AccountListingCreate(
        title="Legacy",
        level=1,
        cars_count=1,
        game_currency="0",
        email_binding="unknown",
        description="Test account",
        price_af_coins=100,
        image_url="/test.jpg",
    )
    legacy = await services.create_account_listing(db, seller, legacy_payload)
    assert len(await routes.list_account_listings(db)) == 1
    db.session.rollback()
    configuration.account_sales_enabled = False
    assert await routes.list_account_listings(db) == []
    for operation in (
        services.set_listing_publication(db, seller, item.id, True),
        services.create_account_listing(db, seller, legacy_payload),
        services.update_account_listing(
            db, seller, legacy.id, AccountListingUpdate(status="active")
        ),
        services.delete_account_listing(db, seller, legacy.id),
        services.create_listing_price_offer(db, buyer, item.id, Decimal(50)),
    ):
        with pytest.raises(HTTPException) as error:
            await operation
        assert error.value.status_code == 503
    _, visible = content_catalog.catalogue("unique")
    # The DB forbids account/unique today. Also assert the discovery predicate
    # explicitly excludes accounts, without weakening that database invariant.
    assert "product_kind" in str(select(Listing.id).where(*visible).compile())
    assert (await db.scalars(select(Listing).where(*visible))).all() == []
    db.session.rollback()
    with db.session.begin():
        assert db.session.get(AccountListing, legacy.id).status == "active"
    configuration.account_sales_enabled = True
    assert len(await routes.list_account_listings(db)) == 1
