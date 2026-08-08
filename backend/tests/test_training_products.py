import uuid
from decimal import Decimal
import pytest
from fastapi import HTTPException

from app.models import AccountListing, Base, TrainingProduct, User
from app.schemas import TrainingProductCreate, TrainingProductOut
from app.services import create_training_product


class Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class Session:
    def __init__(self):
        self.added = []

    def begin(self):
        return Transaction()

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


def payload():
    return TrainingProductCreate(
        title="Премиальное обучение",
        short_description="Краткое описание программы",
        full_description="Полное описание программы без закрытых материалов",
        cover_url="/uploads/training.webp",
        product_type="personal",
        price_af_coins=Decimal("250"),
        published=True,
        pinned=True,
    )


def test_training_has_separate_table_and_legacy_accounts_are_preserved():
    assert TrainingProduct.__tablename__ == "training_products"
    assert AccountListing.__tablename__ == "account_listings"
    assert "account_listings" in Base.metadata.tables
    assert "training_products" in Base.metadata.tables


def test_public_training_schema_contains_no_private_materials():
    fields = set(TrainingProductOut.model_fields)
    assert "private_materials" not in fields
    assert "delivery_payload" not in fields
    automatic = payload().model_copy(update={"product_type": "automatic"})
    assert automatic.product_type == "automatic"


@pytest.mark.asyncio
async def test_non_admin_cannot_create_training_even_via_service():
    user = User(id=uuid.uuid4(), telegram_id=1, first_name="User", role="user")
    with pytest.raises(HTTPException) as error:
        await create_training_product(Session(), user, payload())
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_create_pinned_training_for_free():
    admin = User(id=uuid.uuid4(), telegram_id=2, first_name="Admin", role="admin")
    session = Session()
    product = await create_training_product(session, admin, payload())
    assert product.pinned is True
    assert product.product_type == "personal"
    assert product.price_af_coins == Decimal("250.00")
    assert not any(item.__class__.__name__ == "WalletTransaction" for item in session.added)
