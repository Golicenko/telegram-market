"""Real persisted SQLite models + route authorization; no Telegram/network calls."""
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.schema import CreateTable

from test_chat_lifecycle_db import db
from app.models import TrainingProduct, TrainingPurchase, TrainingMaterial
from app.routes import training_purchase_access, open_purchased_training_materials


@pytest.fixture
def library(db):
    session, buyer, seller, _ = db
    for model in (TrainingProduct, TrainingPurchase, TrainingMaterial):
        session.session.execute(CreateTable(model.__table__))
    seller.username = "teacher_name"
    product = TrainingProduct(id=uuid.uuid4(), admin_id=seller.id, title="Course",
        short_description="Short", full_description="Full", cover_url="/cover.webp",
        product_type="personal", price_af_coins=50, published=False, deleted_at=datetime.now(UTC))
    purchase = TrainingPurchase(id=uuid.uuid4(), product_id=product.id, buyer_id=buyer.id,
        seller_id=seller.id, buyer_telegram_id=buyer.telegram_id, buyer_display_name="Buyer",
        buyer_username=None, product_type="personal", title_snapshot="Purchased course",
        cover_url_snapshot="/cover.webp", price_af_coins=50, seller_payout=35,
        platform_commission=15, payment_status="paid", status="awaiting_start")
    session.session.add_all([product, purchase])
    session.session.commit()
    return session, buyer, seller, product, purchase


@pytest.mark.asyncio
async def test_archived_purchase_survives_reopen_and_contact_is_real_owner(library):
    session, buyer, seller, product, purchase = library
    result = await training_purchase_access(purchase.id, buyer, session)
    assert result["purchase"].title_snapshot == "Purchased course"
    assert result["contact_url"] == "https://t.me/teacher_name"
    assert result["access_allowed"] is True
    session.session.expire_all()
    assert (await training_purchase_access(purchase.id, buyer, session))["purchase"].id == purchase.id
    for username in (None, "invalid/name"):
        seller.username = username
        session.session.commit()
        assert (await training_purchase_access(purchase.id, buyer, session))["contact_url"] is None


@pytest.mark.asyncio
async def test_access_denies_nonbuyer_and_missing_purchase_and_personal_has_no_materials(library):
    session, buyer, seller, product, purchase = library
    for endpoint in (training_purchase_access, open_purchased_training_materials):
        with pytest.raises(HTTPException) as denied:
            await endpoint(purchase.id, seller, session)
        assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as missing:
        await training_purchase_access(uuid.uuid4(), buyer, session)
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as denied:
        await open_purchased_training_materials(purchase.id, buyer, session)
    assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_library_never_exposes_delivery_reference(library):
    session, buyer, seller, product, purchase = library
    purchase.product_type = "automatic"
    purchase.status = "completed"
    session.session.add(TrainingMaterial(product_id=product.id, title="Video", material_type="video",
        delivery_reference="private-telegram-file-id", position=0))
    session.session.commit()
    access = await training_purchase_access(purchase.id, buyer, session)
    material = access["purchase"].materials[0].model_dump()
    assert material["title"] == "Video"
    assert "delivery_reference" not in material
    assert access["contact_url"] is None
