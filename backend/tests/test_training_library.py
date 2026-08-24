import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models import TrainingMaterial, TrainingProduct, TrainingPurchase, User, Wallet, WalletTransaction
from app.schemas import TrainingMaterialPublicOut
from app.services import begin_training_delivery, purchase_training_product, update_training_purchase_status


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSession:
    def __init__(self, scalar_values=()):
        self.scalar_values = list(scalar_values)
        self.added = []

    def begin(self):
        return FakeTransaction()

    async def scalar(self, _query):
        return self.scalar_values.pop(0) if self.scalar_values else None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if hasattr(value, "id") and value.id is None:
                value.id = uuid.uuid4()


def wallet(user_id, purchased="0", earned="0"):
    return Wallet(
        user_id=user_id,
        purchased_balance=Decimal(purchased),
        earned_balance=Decimal(earned),
        purchased_frozen_balance=Decimal("0"),
        earned_frozen_balance=Decimal("0"),
        total_earned=Decimal(earned),
        version=0,
    )


def product(admin_id, product_type="automatic", price="100"):
    return TrainingProduct(
        id=uuid.uuid4(), admin_id=admin_id, title="Курс", short_description="Краткое описание",
        full_description="Полное описание курса", cover_url="/uploads/course.jpg",
        product_type=product_type, price_af_coins=Decimal(price), availability="available",
        published=True, pinned=False,
    )


def test_public_material_schema_never_exposes_delivery_reference():
    material = TrainingMaterial(
        id=uuid.uuid4(), product_id=uuid.uuid4(), title="Закрытый файл", material_type="document",
        delivery_reference="telegram-secret-file-id", mime_type="application/pdf", file_size=1234,
        metadata_json={}, position=0, is_active=True,
    )
    payload = TrainingMaterialPublicOut.model_validate(material).model_dump()
    assert payload["title"] == "Закрытый файл"
    assert "delivery_reference" not in payload


def test_one_purchase_per_product_and_buyer_is_enforced_by_database_model():
    constraints = {getattr(item, "name", None) for item in TrainingPurchase.__table__.constraints}
    assert "uq_training_purchase_product_buyer" in constraints


@pytest.mark.asyncio
async def test_automatic_purchase_is_atomic_and_retry_is_idempotent():
    buyer = User(id=uuid.uuid4(), telegram_id=1, first_name="Покупатель", role="user")
    seller = User(id=uuid.uuid4(), telegram_id=2, first_name="Администратор", role="admin")
    course = product(seller.id, "automatic", "100")
    buyer_wallet = wallet(buyer.id, purchased="120")
    seller_wallet = wallet(seller.id)
    session = FakeSession([course, None, uuid.uuid4(), buyer_wallet, seller_wallet])

    purchase, created = await purchase_training_product(session, buyer, course.id)

    assert created is True
    assert purchase.status == "completed"
    assert buyer_wallet.available_balance == Decimal("20.00")
    assert seller_wallet.earned_balance == Decimal("70.00")
    transactions = [item for item in session.added if isinstance(item, WalletTransaction)]
    assert [item.amount for item in transactions] == [Decimal("-100.00"), Decimal("70.00")]
    assert all(item.related_training_purchase_id == purchase.id for item in transactions)

    retry_session = FakeSession([course, purchase])
    retried, retry_created = await purchase_training_product(retry_session, buyer, course.id)
    assert retried is purchase
    assert retry_created is False
    assert buyer_wallet.available_balance == Decimal("20.00")
    assert not any(isinstance(item, WalletTransaction) for item in retry_session.added)


@pytest.mark.asyncio
async def test_automatic_course_cannot_charge_before_materials_exist():
    buyer = User(id=uuid.uuid4(), telegram_id=1, first_name="Покупатель", role="user")
    course = product(uuid.uuid4(), "automatic", "100")
    buyer_wallet = wallet(buyer.id, purchased="100")
    session = FakeSession([course, None, None])

    with pytest.raises(HTTPException) as error:
        await purchase_training_product(session, buyer, course.id)

    assert error.value.status_code == 409
    assert buyer_wallet.available_balance == Decimal("100.00")
    assert not any(isinstance(item, WalletTransaction) for item in session.added)


@pytest.mark.asyncio
async def test_personal_training_settles_only_after_completion():
    admin = User(id=uuid.uuid4(), telegram_id=2, first_name="Администратор", role="admin")
    buyer_id = uuid.uuid4()
    buyer_wallet = wallet(buyer_id, purchased="0")
    buyer_wallet.purchased_frozen_balance = Decimal("100")
    seller_wallet = wallet(admin.id)
    purchase = TrainingPurchase(
        id=uuid.uuid4(), product_id=uuid.uuid4(), buyer_id=buyer_id, seller_id=admin.id,
        product_type="personal", title_snapshot="Персональный курс", cover_url_snapshot="/cover.jpg",
        price_af_coins=Decimal("100"), seller_payout=Decimal("70"), platform_commission=Decimal("30"),
        status="awaiting_start", delivery_status="not_applicable", purchased_frozen_amount=Decimal("100"),
        earned_frozen_amount=Decimal("0"), delivery_attempts=0,
    )
    started = await update_training_purchase_status(FakeSession([purchase]), admin, purchase.id, "in_progress")
    assert started.status == "in_progress"

    session = FakeSession([purchase, buyer_wallet, seller_wallet])

    completed = await update_training_purchase_status(session, admin, purchase.id, "completed")

    assert completed.status == "completed"
    assert completed.settled_at is not None
    assert buyer_wallet.frozen_balance == Decimal("0.00")
    assert seller_wallet.earned_balance == Decimal("70.00")


@pytest.mark.asyncio
async def test_redelivery_requires_owner_and_enforces_cooldown_and_lock():
    buyer_id = uuid.uuid4()
    purchase = TrainingPurchase(
        id=uuid.uuid4(), product_id=uuid.uuid4(), buyer_id=buyer_id, seller_id=uuid.uuid4(),
        product_type="automatic", title_snapshot="Курс", cover_url_snapshot="/cover.jpg",
        price_af_coins=Decimal("100"), seller_payout=Decimal("70"), platform_commission=Decimal("30"),
        status="completed", delivery_status="delivered", purchased_frozen_amount=Decimal("0"),
        earned_frozen_amount=Decimal("0"), delivery_attempts=0,
    )
    await begin_training_delivery(FakeSession([purchase]), buyer_id, purchase.id, cooldown_seconds=300)
    assert purchase.delivery_status == "sending"
    assert purchase.delivery_attempts == 1

    with pytest.raises(HTTPException) as locked:
        await begin_training_delivery(FakeSession([purchase]), buyer_id, purchase.id, cooldown_seconds=300)
    assert locked.value.status_code == 409

    purchase.delivery_lock_until = None
    with pytest.raises(HTTPException) as cooling_down:
        await begin_training_delivery(FakeSession([purchase]), buyer_id, purchase.id, cooldown_seconds=300)
    assert cooling_down.value.status_code == 429

    purchase.last_delivery_requested_at = datetime.now(UTC)
    with pytest.raises(HTTPException) as stranger:
        await begin_training_delivery(FakeSession([purchase]), uuid.uuid4(), purchase.id, cooldown_seconds=300)
    assert stranger.value.status_code == 404
