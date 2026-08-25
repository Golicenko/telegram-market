import uuid
from decimal import Decimal
import pytest
from fastapi import HTTPException
from sqlalchemy import Text

from app import routes
from app.models import AccountListing, AdminAction, Base, TrainingProduct, TrainingPurchase, User
from app.schemas import TrainingProductCreate, TrainingProductOut, TrainingProductUpdate
from app.services import create_training_product, delete_training_product, set_training_product_state, update_training_product


class Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class Session:
    def __init__(self, scalar_values=()):
        self.added = []
        self.scalar_values = list(scalar_values)

    def begin(self):
        return Transaction()

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def scalar(self, _query):
        return self.scalar_values.pop(0) if self.scalar_values else None


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


def test_training_text_is_not_artificially_truncated_and_price_is_positive():
    long_text = "Т" * 20_000
    value = payload().model_copy(update={
        "title": long_text,
        "short_description": long_text,
        "full_description": long_text,
        "price_af_coins": Decimal("0.01"),
    })
    validated = TrainingProductCreate.model_validate(value.model_dump())
    assert validated.title == long_text
    assert validated.price_af_coins == Decimal("0.01")
    assert isinstance(TrainingProduct.title.type, Text)
    assert isinstance(TrainingPurchase.title_snapshot.type, Text)
    with pytest.raises(Exception):
        TrainingProductCreate.model_validate({**value.model_dump(), "price_af_coins": 0})


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


@pytest.mark.asyncio
async def test_automatic_training_is_created_as_draft_until_material_exists():
    admin = User(id=uuid.uuid4(), telegram_id=2, first_name="Admin", role="admin")
    automatic = payload().model_copy(update={"product_type": "automatic", "published": True})
    with pytest.raises(HTTPException) as error:
        await create_training_product(Session(), admin, automatic)
    assert error.value.status_code == 409
    assert "материал" in error.value.detail.lower()


@pytest.mark.asyncio
async def test_automatic_training_cannot_be_published_without_saved_material():
    admin = User(id=uuid.uuid4(), telegram_id=2, first_name="Admin", role="admin")
    product = TrainingProduct(
        id=uuid.uuid4(), admin_id=admin.id, title="Автокурс", short_description="Кратко",
        full_description="Полностью", cover_url="/cover.jpg", product_type="automatic",
        price_af_coins=Decimal("100"), availability="available", published=False, pinned=False,
    )
    with pytest.raises(HTTPException) as update_error:
        await update_training_product(Session([product, None]), admin, product.id, TrainingProductUpdate(published=True))
    assert update_error.value.status_code == 409
    assert product.published is False

    with pytest.raises(HTTPException) as state_error:
        await set_training_product_state(Session([product, None]), admin, product.id, "publish")
    assert state_error.value.status_code == 409
    assert product.published is False


@pytest.mark.asyncio
async def test_automatic_training_can_be_published_after_material_is_saved():
    admin = User(id=uuid.uuid4(), telegram_id=2, first_name="Admin", role="admin")
    product = TrainingProduct(
        id=uuid.uuid4(), admin_id=admin.id, title="Автокурс", short_description="Кратко",
        full_description="Полностью", cover_url="/cover.jpg", product_type="automatic",
        price_af_coins=Decimal("100"), availability="available", published=False, pinned=False,
    )
    updated = await update_training_product(
        Session([product, uuid.uuid4()]), admin, product.id, TrainingProductUpdate(published=True)
    )
    assert updated.published is True


@pytest.mark.asyncio
async def test_deleted_training_is_soft_deleted_and_excluded_from_admin_management():
    admin = User(id=uuid.uuid4(), telegram_id=2, first_name="Admin", role="admin")
    product = TrainingProduct(
        id=uuid.uuid4(), admin_id=admin.id, title="Курс", short_description="Кратко",
        full_description="Полностью", cover_url="/cover.jpg", product_type="personal",
        price_af_coins=Decimal("100"), availability="available", published=True, pinned=True,
    )
    delete_session = Session([product])
    await delete_training_product(delete_session, admin, product.id)
    assert product.deleted_at is not None
    assert product.published is False
    assert product.pinned is False
    assert any(isinstance(item, AdminAction) and item.action == "delete_training_product" for item in delete_session.added)

    class Rows:
        def all(self):
            return []

    class ManagementSession:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Rows()

    management_session = ManagementSession()
    assert await routes.manage_training_products("all", admin, management_session) == []
    assert "training_products.deleted_at IS NULL" in str(management_session.statement)
