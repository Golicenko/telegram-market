import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Awaitable, Callable

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import (
    AccountListing,
    AdminAction,
    AdminBalanceAdjustment,
    CartItem,
    Conversation,
    ConversationMessage,
    Deal,
    DealMessage,
    Listing,
    ListingImage,
    Notification,
    PriceOffer,
    StarPayment,
    StarPaymentIntent,
    SupportCaseEvent,
    SupportMessage,
    SupportTicket,
    TrainingMaterial,
    TrainingProduct,
    TrainingPurchase,
    User,
    Wallet,
    WalletTransaction,
    WithdrawalRequest,
)


AF = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(value).quantize(AF, rounding=ROUND_HALF_UP)


def settlement_amounts(price: Decimal) -> tuple[Decimal, Decimal]:
    seller_percent = Decimal(get_settings().seller_payout_percent) / Decimal("100")
    seller_payout = money(money(price) * seller_percent)
    return seller_payout, money(money(price) - seller_payout)


def wallet_transaction(
    wallet: Wallet,
    transaction_type: str,
    amount: Decimal,
    available_before: Decimal,
    frozen_before: Decimal,
    description: str,
    *,
    deal_id: uuid.UUID | None = None,
    withdrawal_id: uuid.UUID | None = None,
    training_purchase_id: uuid.UUID | None = None,
    external_reference: str | None = None,
) -> WalletTransaction:
    return WalletTransaction(
        user_id=wallet.user_id,
        transaction_type=transaction_type,
        amount=money(amount),
        available_before=money(available_before),
        available_after=money(wallet.available_balance),
        frozen_before=money(frozen_before),
        frozen_after=money(wallet.frozen_balance),
        related_deal_id=deal_id,
        related_withdrawal_id=withdrawal_id,
        related_training_purchase_id=training_purchase_id,
        external_reference=external_reference,
        description=description,
    )


def wallet_snapshot(wallet: Wallet) -> tuple[Decimal, Decimal]:
    return money(wallet.available_balance), money(wallet.frozen_balance)


def hold_for_purchase(wallet: Wallet, amount: Decimal) -> tuple[Decimal, Decimal]:
    """Move spendable funds into protected buckets, purchased funds first."""
    amount = money(amount)
    if wallet.available_balance < amount:
        raise HTTPException(status_code=402, detail=f"Не хватает {money(amount - wallet.available_balance)} AF Coins")
    purchased = min(money(wallet.purchased_balance), amount)
    earned = money(amount - purchased)
    wallet.purchased_balance = money(wallet.purchased_balance - purchased)
    wallet.earned_balance = money(wallet.earned_balance - earned)
    wallet.purchased_frozen_balance = money(wallet.purchased_frozen_balance + purchased)
    wallet.earned_frozen_balance = money(wallet.earned_frozen_balance + earned)
    return purchased, earned


def release_purchase_hold(wallet: Wallet, purchased: Decimal, earned: Decimal) -> None:
    purchased, earned = money(purchased), money(earned)
    if wallet.purchased_frozen_balance < purchased or wallet.earned_frozen_balance < earned:
        raise HTTPException(status_code=409, detail="Состояние защищённых средств не совпадает")
    wallet.purchased_frozen_balance = money(wallet.purchased_frozen_balance - purchased)
    wallet.earned_frozen_balance = money(wallet.earned_frozen_balance - earned)
    wallet.purchased_balance = money(wallet.purchased_balance + purchased)
    wallet.earned_balance = money(wallet.earned_balance + earned)


def consume_purchase_hold(wallet: Wallet, purchased: Decimal, earned: Decimal) -> None:
    purchased, earned = money(purchased), money(earned)
    if wallet.purchased_frozen_balance < purchased or wallet.earned_frozen_balance < earned:
        raise HTTPException(status_code=409, detail="Состояние защищённых средств не совпадает")
    wallet.purchased_frozen_balance = money(wallet.purchased_frozen_balance - purchased)
    wallet.earned_frozen_balance = money(wallet.earned_frozen_balance - earned)


def debit_spendable(wallet: Wallet, amount: Decimal) -> tuple[Decimal, Decimal]:
    purchased, earned = hold_for_purchase(wallet, amount)
    consume_purchase_hold(wallet, purchased, earned)
    return purchased, earned


async def create_notification(session: AsyncSession, user_id: uuid.UUID, kind: str, title: str, body: str, payload: dict | None = None) -> Notification:
    notification = Notification(user_id=user_id, notification_type=kind, title=title, body=body, payload=payload or {})
    session.add(notification)
    return notification


async def create_listing(
    session: AsyncSession,
    seller: User,
    payload,
    *,
    listing_type: str,
    pinned: bool = False,
) -> Listing:
    settings = get_settings()
    if listing_type == "unique" and seller.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can create unique listings")

    async with session.begin():
        now = datetime.now(UTC)
        admin_pinned = seller.role == "admin" and listing_type == "unique" and pinned
        listing = Listing(
            seller_id=seller.id,
            listing_type=listing_type,
            status="active",
            brand=payload.brand,
            model=payload.model or "",
            power_hp=payload.power_hp,
            max_speed_kph=payload.max_speed_kph,
            description=payload.description.strip(),
            price_af_coins=money(payload.price_af_coins),
            delivery_time_estimate=payload.delivery_time_estimate,
            pinned=admin_pinned,
            pinned_until=now + timedelta(hours=settings.listing_promotion_hours) if admin_pinned else None,
        )
        session.add(listing)
        await session.flush()
        for position, url in enumerate(payload.image_urls):
            session.add(ListingImage(listing_id=listing.id, url=url, position=position))
        if listing_type == "unique":
            session.add(AdminAction(admin_id=seller.id, action="create_unique_listing", target_type="listing", target_id=listing.id))
    await session.refresh(listing)
    return listing


async def charge_listing_promotion(session: AsyncSession, actor: User, listing: Listing) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    if listing.seller_id != actor.id:
        raise HTTPException(status_code=403, detail="Вы можете закреплять только свои объявления")
    if listing.status != "active":
        raise HTTPException(status_code=409, detail="Можно закрепить только активное непроданное объявление")
    if listing.pinned and listing.pinned_until and listing.pinned_until > now:
        return
    listing.pinned = True
    listing.pinned_until = now + timedelta(hours=settings.listing_promotion_hours)
    if actor.role == "admin" and listing.listing_type == "unique":
        session.add(AdminAction(admin_id=actor.id, action="pin_listing_free", target_type="listing", target_id=listing.id))
        return
    cost = money(settings.listing_promotion_cost_af_coins)
    wallet = await session.scalar(select(Wallet).where(Wallet.user_id == actor.id).with_for_update())
    if not wallet or wallet.available_balance < cost:
        raise HTTPException(status_code=402, detail="Недостаточно AF Coins. Пополните баланс, чтобы закрепить объявление.")
    before_available, before_frozen = wallet_snapshot(wallet)
    debit_spendable(wallet, cost)
    wallet.version += 1
    session.add(
        wallet_transaction(
            wallet,
            "listing_promotion",
            -cost,
            before_available,
            before_frozen,
            f"Закрепление объявления до {listing.pinned_until.isoformat()}",
            external_reference=f"listing-promotion:{listing.id}:{listing.pinned_until.isoformat()}",
        )
    )


async def promote_listing(session: AsyncSession, actor: User, listing_id: uuid.UUID) -> Listing:
    async with session.begin():
        listing = await session.scalar(select(Listing).where(Listing.id == listing_id).with_for_update())
        if not listing or listing.status != "active":
            raise HTTPException(status_code=404, detail="Active listing not found")
        await charge_listing_promotion(session, actor, listing)
    return listing


async def update_listing(session: AsyncSession, actor: User, listing_id: uuid.UUID, payload) -> Listing:
    async with session.begin():
        listing = await session.scalar(select(Listing).where(Listing.id == listing_id).with_for_update())
        if not listing or listing.status == "deleted":
            raise HTTPException(status_code=404, detail="Listing not found")
        if actor.role != "admin" and (listing.seller_id != actor.id or listing.listing_type != "regular"):
            raise HTTPException(status_code=403, detail="You cannot edit this listing")
        if listing.status == "reserved":
            raise HTTPException(status_code=409, detail="Reserved listing cannot be edited")
        changes = payload.model_dump(exclude_unset=True, exclude={"image_urls"})
        for field, value in changes.items():
            if field == "price_af_coins":
                value = money(value)
            if field == "model" and value is None:
                value = ""
            setattr(listing, field, value)
        if payload.image_urls is not None:
            await session.execute(delete(ListingImage).where(ListingImage.listing_id == listing.id))
            for position, url in enumerate(payload.image_urls):
                session.add(ListingImage(listing_id=listing.id, url=url, position=position))
        if actor.role == "admin":
            session.add(AdminAction(admin_id=actor.id, action="update_listing", target_type="listing", target_id=listing.id))
    return listing


async def delete_listing(session: AsyncSession, actor: User, listing_id: uuid.UUID) -> None:
    async with session.begin():
        listing = await session.scalar(select(Listing).where(Listing.id == listing_id).with_for_update())
        if not listing or listing.status == "deleted":
            raise HTTPException(status_code=404, detail="Listing not found")
        if actor.role != "admin" and listing.seller_id != actor.id:
            raise HTTPException(status_code=403, detail="You cannot delete this listing")
        active_deal = await session.scalar(
            select(Deal.id).where(Deal.listing_id == listing.id, Deal.status.not_in(["completed", "cancelled"]))
        )
        if active_deal:
            raise HTTPException(status_code=409, detail="Listing with an active deal cannot be deleted")
        listing.status = "deleted"
        listing.deleted_at = datetime.now(UTC)
        await session.execute(delete(CartItem).where(CartItem.listing_id == listing.id))
        if actor.role == "admin":
            session.add(AdminAction(admin_id=actor.id, action="delete_listing", target_type="listing", target_id=listing.id))


async def set_listing_publication(session: AsyncSession, admin: User, listing_id: uuid.UUID, published: bool) -> Listing:
    async with session.begin():
        listing = await session.scalar(select(Listing).where(Listing.id == listing_id).with_for_update())
        if not listing or listing.status in {"deleted", "sold", "reserved"}:
            raise HTTPException(status_code=409, detail="Listing publication state cannot be changed")
        listing.status = "active" if published else "paused"
        session.add(AdminAction(admin_id=admin.id, action="publish_listing" if published else "unpublish_listing", target_type="listing", target_id=listing.id))
    return listing


async def update_special_listing(session: AsyncSession, admin: User, listing_id: uuid.UUID, payload) -> Listing:
    return await update_listing(session, admin, listing_id, payload)


async def delete_special_listing(session: AsyncSession, admin: User, listing_id: uuid.UUID) -> None:
    await delete_listing(session, admin, listing_id)


async def create_account_listing(session: AsyncSession, admin: User, payload) -> AccountListing:
    async with session.begin():
        account = AccountListing(
            seller_id=admin.id,
            status="active",
            title=payload.title.strip(),
            level=payload.level,
            cars_count=payload.cars_count,
            game_currency=payload.game_currency.strip(),
            extra_currency=payload.extra_currency.strip() if payload.extra_currency else None,
            game_assets=payload.game_assets.strip() if payload.game_assets else None,
            email_binding=payload.email_binding,
            auto_delivery=payload.auto_delivery,
            description=payload.description.strip(),
            price_af_coins=money(payload.price_af_coins),
            image_url=payload.image_url,
        )
        session.add(account)
        await session.flush()
        session.add(AdminAction(admin_id=admin.id, action="create_account_listing", target_type="account_listing", target_id=account.id))
    return account


async def update_account_listing(session: AsyncSession, admin: User, account_id: uuid.UUID, payload) -> AccountListing:
    async with session.begin():
        account = await session.scalar(select(AccountListing).where(AccountListing.id == account_id).with_for_update())
        if not account or account.status == "deleted":
            raise HTTPException(status_code=404, detail="Account listing not found")
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            if field == "price_af_coins" and value is not None:
                value = money(value)
            if isinstance(value, str):
                value = value.strip()
            setattr(account, field, value)
        session.add(AdminAction(admin_id=admin.id, action="update_account_listing", target_type="account_listing", target_id=account.id))
    return account


async def delete_account_listing(session: AsyncSession, admin: User, account_id: uuid.UUID) -> None:
    async with session.begin():
        account = await session.scalar(select(AccountListing).where(AccountListing.id == account_id).with_for_update())
        if not account or account.status == "deleted":
            raise HTTPException(status_code=404, detail="Account listing not found")
        account.status = "deleted"
        session.add(AdminAction(admin_id=admin.id, action="delete_account_listing", target_type="account_listing", target_id=account.id))


async def create_training_product(session: AsyncSession, admin: User, payload) -> TrainingProduct:
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="Только администратор может создавать обучение")
    async with session.begin():
        product = TrainingProduct(
            admin_id=admin.id,
            title=payload.title.strip(),
            short_description=payload.short_description.strip(),
            full_description=payload.full_description.strip(),
            cover_url=payload.cover_url.strip(),
            promo_video_url=payload.promo_video_url.strip() if payload.promo_video_url else None,
            product_type=payload.product_type,
            price_af_coins=money(payload.price_af_coins),
            availability=payload.availability,
            published=payload.published,
            pinned=payload.pinned,
        )
        session.add(product)
        await session.flush()
        session.add(AdminAction(admin_id=admin.id, action="create_training_product", target_type="training_product", target_id=product.id))
    return product


async def update_training_product(session: AsyncSession, admin: User, product_id: uuid.UUID, payload) -> TrainingProduct:
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="Требуется роль администратора")
    async with session.begin():
        product = await session.scalar(select(TrainingProduct).where(TrainingProduct.id == product_id).with_for_update())
        if not product:
            raise HTTPException(status_code=404, detail="Обучение не найдено")
        if product.admin_id != admin.id:
            raise HTTPException(status_code=403, detail="Можно изменять только собственные обучения")
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            if field == "price_af_coins" and value is not None:
                value = money(value)
            if isinstance(value, str):
                value = value.strip()
            setattr(product, field, value)
        session.add(AdminAction(admin_id=admin.id, action="update_training_product", target_type="training_product", target_id=product.id, metadata_json={"fields": sorted(changes)}))
    return product


async def delete_training_product(session: AsyncSession, admin: User, product_id: uuid.UUID) -> None:
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="Требуется роль администратора")
    async with session.begin():
        product = await session.scalar(select(TrainingProduct).where(TrainingProduct.id == product_id).with_for_update())
        if not product or product.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Обучение не найдено")
        if product.admin_id != admin.id:
            raise HTTPException(status_code=403, detail="Можно удалять только собственные обучения")
        product.published = False
        product.pinned = False
        product.deleted_at = datetime.now(UTC)
        session.add(AdminAction(admin_id=admin.id, action="delete_training_product", target_type="training_product", target_id=product.id))


async def set_training_product_state(
    session: AsyncSession, admin: User, product_id: uuid.UUID, action: str
) -> TrainingProduct:
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="Требуется роль администратора")
    if action not in {"publish", "hide", "pin", "unpin"}:
        raise HTTPException(status_code=400, detail="Неизвестное действие")
    async with session.begin():
        product = await session.scalar(select(TrainingProduct).where(TrainingProduct.id == product_id).with_for_update())
        if not product:
            raise HTTPException(status_code=404, detail="Обучение не найдено")
        if product.admin_id != admin.id:
            raise HTTPException(status_code=403, detail="Можно управлять только собственными обучениями")
        if action == "publish":
            product.deleted_at = None
            product.published = True
        elif action == "hide":
            product.published = False
            product.pinned = False
        elif action == "pin":
            if product.deleted_at is not None:
                raise HTTPException(status_code=409, detail="Сначала восстановите обучение")
            product.pinned = True
        else:
            product.pinned = False
        session.add(AdminAction(admin_id=admin.id, action=f"{action}_training_product", target_type="training_product", target_id=product.id))
    return product


async def create_training_material(session: AsyncSession, admin: User, product_id: uuid.UUID, payload) -> TrainingMaterial:
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="Требуется роль администратора")
    async with session.begin():
        product = await session.scalar(select(TrainingProduct).where(TrainingProduct.id == product_id).with_for_update())
        if not product or product.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Обучение не найдено")
        if product.admin_id != admin.id:
            raise HTTPException(status_code=403, detail="Можно изменять только собственные обучения")
        if product.product_type != "automatic":
            raise HTTPException(status_code=409, detail="Материалы доступны только для автовыдачи")
        material = TrainingMaterial(
            product_id=product.id,
            title=payload.title.strip(),
            material_type=payload.material_type,
            delivery_reference=payload.delivery_reference.strip(),
            mime_type=payload.mime_type,
            file_size=payload.file_size,
            metadata_json=payload.metadata_json,
            position=payload.position,
        )
        session.add(material)
        await session.flush()
        session.add(AdminAction(admin_id=admin.id, action="create_training_material", target_type="training_material", target_id=material.id))
    return material


async def update_training_material(session: AsyncSession, admin: User, material_id: uuid.UUID, payload) -> TrainingMaterial:
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="Требуется роль администратора")
    async with session.begin():
        material = await session.scalar(select(TrainingMaterial).where(TrainingMaterial.id == material_id).with_for_update())
        if not material or not material.is_active:
            raise HTTPException(status_code=404, detail="Материал не найден")
        product = await session.get(TrainingProduct, material.product_id)
        if not product or product.admin_id != admin.id:
            raise HTTPException(status_code=403, detail="Нет доступа к материалу")
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            if isinstance(value, str):
                value = value.strip()
            setattr(material, field, value)
        session.add(AdminAction(admin_id=admin.id, action="update_training_material", target_type="training_material", target_id=material.id, metadata_json={"fields": sorted(changes)}))
    return material


async def delete_training_material(session: AsyncSession, admin: User, material_id: uuid.UUID) -> None:
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="Требуется роль администратора")
    async with session.begin():
        material = await session.scalar(select(TrainingMaterial).where(TrainingMaterial.id == material_id).with_for_update())
        if not material or not material.is_active:
            raise HTTPException(status_code=404, detail="Материал не найден")
        product = await session.get(TrainingProduct, material.product_id)
        if not product or product.admin_id != admin.id:
            raise HTTPException(status_code=403, detail="Нет доступа к материалу")
        material.is_active = False
        session.add(AdminAction(admin_id=admin.id, action="delete_training_material", target_type="training_material", target_id=material.id))


def credit_training_seller(wallet: Wallet, amount: Decimal) -> None:
    wallet.earned_balance = money(wallet.earned_balance + amount)
    wallet.total_earned = money(wallet.total_earned + amount)


async def purchase_training_product(
    session: AsyncSession,
    buyer: User,
    product_id: uuid.UUID,
    *,
    telegram_payment_charge_id: str | None = None,
    expected_price: Decimal | None = None,
) -> tuple[TrainingPurchase, bool]:
    now = datetime.now(UTC)
    async with session.begin():
        product = await session.scalar(select(TrainingProduct).where(TrainingProduct.id == product_id).with_for_update())
        if not product or product.deleted_at is not None or not product.published:
            raise HTTPException(status_code=404, detail="Обучение недоступно")
        if product.availability != "available":
            raise HTTPException(status_code=409, detail="Обучение сейчас недоступно для покупки")
        if expected_price is not None and money(product.price_af_coins) != money(expected_price):
            raise HTTPException(status_code=409, detail="Цена обучения изменилась во время оплаты")
        if product.admin_id == buyer.id:
            raise HTTPException(status_code=409, detail="Нельзя купить собственное обучение")
        existing = await session.scalar(select(TrainingPurchase).where(
            TrainingPurchase.product_id == product.id,
            TrainingPurchase.buyer_id == buyer.id,
        ))
        if existing:
            return existing, False
        if product.product_type == "automatic" and not await session.scalar(
            select(TrainingMaterial.id).where(
                TrainingMaterial.product_id == product.id,
                TrainingMaterial.is_active.is_(True),
            ).limit(1)
        ):
            raise HTTPException(status_code=409, detail="Материалы курса ещё не подготовлены")
        buyer_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id).with_for_update())
        if not buyer_wallet:
            raise HTTPException(status_code=409, detail="Кошелёк пользователя не найден")

        price = money(product.price_af_coins)
        payout, commission = settlement_amounts(price)
        buyer_available_before, buyer_frozen_before = wallet_snapshot(buyer_wallet)
        if product.product_type == "personal":
            purchased_part, earned_part = hold_for_purchase(buyer_wallet, price)
            status_value = "awaiting_start"
            delivery_status = "not_applicable"
            settled_at = None
            completed_at = None
        else:
            purchased_part, earned_part = debit_spendable(buyer_wallet, price)
            status_value = "completed"
            delivery_status = "pending"
            settled_at = now
            completed_at = now

        purchase = TrainingPurchase(
            product_id=product.id,
            buyer_id=buyer.id,
            seller_id=product.admin_id,
            buyer_telegram_id=buyer.telegram_id,
            buyer_display_name=" ".join(filter(None, [buyer.first_name, buyer.last_name])).strip() or "Telegram User",
            buyer_username=buyer.username,
            telegram_payment_charge_id=telegram_payment_charge_id,
            payment_status="paid",
            admin_notification_status="pending" if product.product_type == "personal" else "not_required",
            product_type=product.product_type,
            title_snapshot=product.title,
            cover_url_snapshot=product.cover_url,
            price_af_coins=price,
            seller_payout=payout,
            platform_commission=commission,
            status=status_value,
            delivery_status=delivery_status,
            purchased_frozen_amount=purchased_part if product.product_type == "personal" else Decimal("0"),
            earned_frozen_amount=earned_part if product.product_type == "personal" else Decimal("0"),
            settled_at=settled_at,
            completed_at=completed_at,
        )
        session.add(purchase)
        await session.flush()
        session.add(wallet_transaction(
            buyer_wallet,
            "training_purchase_reserved" if product.product_type == "personal" else "training_purchase",
            -price,
            buyer_available_before,
            buyer_frozen_before,
            f"Покупка обучения: {product.title}",
            training_purchase_id=purchase.id,
            external_reference=f"training:{purchase.id}:buyer",
        ))

        if product.product_type == "automatic":
            seller_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == product.admin_id).with_for_update())
            if not seller_wallet:
                raise HTTPException(status_code=409, detail="Кошелёк продавца не найден")
            seller_available_before, seller_frozen_before = wallet_snapshot(seller_wallet)
            credit_training_seller(seller_wallet, payout)
            session.add(wallet_transaction(
                seller_wallet,
                "training_sale",
                payout,
                seller_available_before,
                seller_frozen_before,
                f"Продажа обучения: {product.title}",
                training_purchase_id=purchase.id,
                external_reference=f"training:{purchase.id}:seller",
            ))

        await create_notification(session, buyer.id, "training_purchase", "Обучение куплено", product.title, {"purchase_id": str(purchase.id)})
        await create_notification(session, product.admin_id, "training_sale", "Новая покупка обучения", product.title, {"purchase_id": str(purchase.id)})
    return purchase, True


async def create_training_payment_intent(
    session: AsyncSession,
    buyer: User,
    product_id: uuid.UUID,
    invoice_factory: Callable[[int, str, str], Awaitable[str]],
) -> StarPaymentIntent:
    now = datetime.now(UTC)
    async with session.begin():
        product = await session.scalar(select(TrainingProduct).where(TrainingProduct.id == product_id).with_for_update())
        if not product or product.deleted_at is not None or not product.published:
            raise HTTPException(status_code=404, detail="Обучение недоступно")
        if product.availability != "available":
            raise HTTPException(status_code=409, detail="Обучение сейчас недоступно для покупки")
        if product.admin_id == buyer.id:
            raise HTTPException(status_code=409, detail="Нельзя купить собственное обучение")
        if await session.scalar(select(TrainingPurchase.id).where(
            TrainingPurchase.product_id == product.id,
            TrainingPurchase.buyer_id == buyer.id,
        )):
            raise HTTPException(status_code=409, detail="Вы уже приобрели это обучение")
        if product.product_type == "automatic" and not await session.scalar(
            select(TrainingMaterial.id).where(
                TrainingMaterial.product_id == product.id,
                TrainingMaterial.is_active.is_(True),
            ).limit(1)
        ):
            raise HTTPException(status_code=409, detail="Материалы курса ещё не подготовлены")
        existing = await session.scalar(
            select(StarPaymentIntent).where(
                StarPaymentIntent.user_id == buyer.id,
                StarPaymentIntent.training_product_id == product.id,
                StarPaymentIntent.purpose == "training_checkout",
                StarPaymentIntent.status == "pending",
            ).with_for_update()
        )
        if existing and existing.expires_at > now:
            if existing.invoice_link:
                return existing
            raise HTTPException(status_code=409, detail="Счёт уже создаётся. Повторите через несколько секунд")
        if existing:
            existing.status = "expired"
        amount = int(money(product.price_af_coins).to_integral_value(rounding=ROUND_CEILING))
        if amount < 1:
            raise HTTPException(status_code=409, detail="Цена обучения должна быть не меньше 1 Telegram Star")
        intent_id = uuid.uuid4()
        intent = StarPaymentIntent(
            id=intent_id,
            user_id=buyer.id,
            invoice_payload=f"autoflow_training:{intent_id}",
            xtr_amount=amount,
            purpose="training_checkout",
            context={
                "title": product.title,
                "product_type": product.product_type,
                "price_af_coins": str(money(product.price_af_coins)),
            },
            training_product_id=product.id,
            seller_id=product.admin_id,
            checkout_status="pending",
            status="pending",
            expires_at=now + timedelta(minutes=30),
        )
        session.add(intent)

    try:
        invoice_link = await invoice_factory(intent.xtr_amount, intent.invoice_payload, product.title)
    except Exception:
        async with session.begin():
            locked = await session.scalar(select(StarPaymentIntent).where(StarPaymentIntent.id == intent.id).with_for_update())
            if locked and locked.status == "pending":
                locked.status = "cancelled"
                locked.checkout_status = "failed"
        raise
    async with session.begin():
        locked = await session.scalar(select(StarPaymentIntent).where(StarPaymentIntent.id == intent.id).with_for_update())
        if not locked or locked.status != "pending":
            raise HTTPException(status_code=409, detail="Счёт больше недоступен")
        locked.invoice_link = invoice_link
    return locked


async def complete_training_payment_intent(
    session: AsyncSession,
    buyer: User,
    intent_id: uuid.UUID,
    telegram_payment_charge_id: str,
) -> tuple[StarPaymentIntent, TrainingPurchase | None, bool]:
    intent = await session.scalar(select(StarPaymentIntent).where(StarPaymentIntent.id == intent_id).with_for_update())
    if not intent or intent.user_id != buyer.id or intent.purpose != "training_checkout":
        await session.rollback()
        raise HTTPException(status_code=404, detail="Счёт обучения не найден")
    if intent.status != "paid":
        await session.rollback()
        raise HTTPException(status_code=409, detail="Telegram ещё не подтвердил оплату")
    if intent.checkout_status == "completed" and intent.training_purchase_id:
        purchase = await session.get(TrainingPurchase, intent.training_purchase_id)
        await session.commit()
        return intent, purchase, False
    product_id = intent.training_product_id
    if not product_id:
        intent.checkout_status = "failed"
        await session.commit()
        raise HTTPException(status_code=409, detail="Счёт не связан с обучением")
    expected_price_value = (intent.context or {}).get("price_af_coins")
    await session.commit()
    try:
        purchase, created = await purchase_training_product(
            session,
            buyer,
            product_id,
            telegram_payment_charge_id=telegram_payment_charge_id,
            expected_price=Decimal(str(expected_price_value)) if expected_price_value is not None else None,
        )
    except IntegrityError:
        await session.rollback()
        purchase = await session.scalar(select(TrainingPurchase).where(
            or_(
                TrainingPurchase.telegram_payment_charge_id == telegram_payment_charge_id,
                and_(TrainingPurchase.product_id == product_id, TrainingPurchase.buyer_id == buyer.id),
            )
        ))
        if not purchase:
            raise
        created = False
        await session.commit()
    except HTTPException:
        async with session.begin():
            locked = await session.scalar(select(StarPaymentIntent).where(StarPaymentIntent.id == intent_id).with_for_update())
            if locked:
                locked.checkout_status = "failed"
        raise
    async with session.begin():
        locked = await session.scalar(select(StarPaymentIntent).where(StarPaymentIntent.id == intent_id).with_for_update())
        locked.training_purchase_id = purchase.id
        locked.checkout_status = "completed"
    return locked, purchase, created


async def update_training_purchase_status(
    session: AsyncSession, admin: User, purchase_id: uuid.UUID, next_status: str
) -> TrainingPurchase:
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="Требуется роль администратора")
    if next_status not in {"in_progress", "completed"}:
        raise HTTPException(status_code=400, detail="Недопустимый статус")
    async with session.begin():
        purchase = await session.scalar(select(TrainingPurchase).where(TrainingPurchase.id == purchase_id).with_for_update())
        if not purchase:
            raise HTTPException(status_code=404, detail="Покупка не найдена")
        if purchase.seller_id != admin.id or purchase.product_type != "personal":
            raise HTTPException(status_code=403, detail="Нет доступа к персональному обучению")
        if purchase.status == next_status:
            return purchase
        if next_status == "in_progress" and purchase.status != "awaiting_start":
            raise HTTPException(status_code=409, detail="Обучение уже начато или завершено")
        if next_status == "completed" and purchase.status != "in_progress":
            raise HTTPException(status_code=409, detail="Сначала начните обучение")
        purchase.status = next_status
        if next_status == "completed":
            buyer_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == purchase.buyer_id).with_for_update())
            seller_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == purchase.seller_id).with_for_update())
            if not buyer_wallet or not seller_wallet:
                raise HTTPException(status_code=409, detail="Кошелёк участника не найден")
            buyer_available_before, buyer_frozen_before = wallet_snapshot(buyer_wallet)
            seller_available_before, seller_frozen_before = wallet_snapshot(seller_wallet)
            consume_purchase_hold(buyer_wallet, purchase.purchased_frozen_amount, purchase.earned_frozen_amount)
            credit_training_seller(seller_wallet, purchase.seller_payout)
            now = datetime.now(UTC)
            purchase.completed_at = now
            purchase.settled_at = now
            session.add(wallet_transaction(
                buyer_wallet, "training_purchase_completed", Decimal("0"), buyer_available_before, buyer_frozen_before,
                f"Персональное обучение завершено: {purchase.title_snapshot}", training_purchase_id=purchase.id,
                external_reference=f"training:{purchase.id}:buyer:completed",
            ))
            session.add(wallet_transaction(
                seller_wallet, "training_sale", purchase.seller_payout, seller_available_before, seller_frozen_before,
                f"Персональное обучение завершено: {purchase.title_snapshot}", training_purchase_id=purchase.id,
                external_reference=f"training:{purchase.id}:seller",
            ))
        await create_notification(
            session, purchase.buyer_id, "training_status", "Статус обучения изменён",
            "Обучение началось" if next_status == "in_progress" else "Обучение завершено",
            {"purchase_id": str(purchase.id), "status": next_status},
        )
        session.add(AdminAction(admin_id=admin.id, action=f"training_{next_status}", target_type="training_purchase", target_id=purchase.id))
    return purchase


async def begin_training_delivery(
    session: AsyncSession, buyer_id: uuid.UUID, purchase_id: uuid.UUID, *, cooldown_seconds: int
) -> TrainingPurchase:
    now = datetime.now(UTC)
    async with session.begin():
        purchase = await session.scalar(select(TrainingPurchase).where(TrainingPurchase.id == purchase_id).with_for_update())
        if not purchase or purchase.buyer_id != buyer_id:
            raise HTTPException(status_code=404, detail="Покупка не найдена")
        if purchase.product_type != "automatic" or purchase.status != "completed":
            raise HTTPException(status_code=409, detail="Повторная выдача для этой покупки недоступна")
        if purchase.delivery_lock_until and purchase.delivery_lock_until > now:
            raise HTTPException(status_code=409, detail="Материалы уже отправляются")
        if purchase.last_delivery_requested_at:
            retry_at = purchase.last_delivery_requested_at + timedelta(seconds=cooldown_seconds)
            if retry_at > now:
                seconds = max(1, int((retry_at - now).total_seconds()))
                raise HTTPException(status_code=429, detail=f"Повторная выдача будет доступна через {seconds} сек.")
        purchase.delivery_status = "sending"
        purchase.delivery_attempts += 1
        purchase.last_delivery_requested_at = now
        purchase.delivery_lock_until = now + timedelta(minutes=2)
    return purchase


async def finish_training_delivery(session: AsyncSession, purchase_id: uuid.UUID, success: bool) -> None:
    async with session.begin():
        purchase = await session.scalar(select(TrainingPurchase).where(TrainingPurchase.id == purchase_id).with_for_update())
        if not purchase:
            return
        purchase.delivery_status = "delivered" if success else "failed"
        purchase.delivery_lock_until = None
        await create_notification(
            session,
            purchase.buyer_id,
            "training_delivery",
            "Материалы отправлены" if success else "Не удалось отправить материалы",
            purchase.title_snapshot,
            {"purchase_id": str(purchase.id), "success": success},
        )


async def get_or_create_conversation(
    session: AsyncSession, buyer: User, listing_id: uuid.UUID, *, create: bool = True
) -> tuple[Conversation | None, User, Listing]:
    async with session.begin():
        listing = await session.scalar(select(Listing).where(Listing.id == listing_id).with_for_update())
        if not listing or listing.status not in {"active", "reserved", "sold"}:
            raise HTTPException(status_code=404, detail="Listing not found")
        if listing.seller_id == buyer.id:
            raise HTTPException(status_code=400, detail="You cannot start a conversation with yourself")
        conversation = await session.scalar(
            select(Conversation).where(
                or_(
                    and_(Conversation.buyer_id == buyer.id, Conversation.seller_id == listing.seller_id),
                    and_(Conversation.buyer_id == listing.seller_id, Conversation.seller_id == buyer.id),
                )
            ).with_for_update()
        )
        if not conversation and create:
            if listing.status != "active":
                raise HTTPException(status_code=409, detail="A new conversation cannot be started for this listing")
            conversation = Conversation(listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id)
            session.add(conversation)
            await session.flush()
        seller = await session.get(User, listing.seller_id)
    return conversation, seller, listing


async def _ensure_deal_conversation_locked(
    session: AsyncSession,
    deal: Deal,
    listing: Listing,
    *,
    unhide_both: bool,
    add_context_if_created: bool = True,
) -> Conversation:
    conversation = None
    if deal.conversation_id:
        conversation = await session.get(Conversation, deal.conversation_id)
    if not conversation:
        conversation = await session.scalar(
            select(Conversation).where(
                or_(
                    and_(Conversation.buyer_id == deal.buyer_id, Conversation.seller_id == deal.seller_id),
                    and_(Conversation.buyer_id == deal.seller_id, Conversation.seller_id == deal.buyer_id),
                )
            ).with_for_update()
        )
    created = conversation is None
    if created:
        conversation = Conversation(
            listing_id=listing.id,
            buyer_id=deal.buyer_id,
            seller_id=deal.seller_id,
        )
        session.add(conversation)
        await session.flush()
    conversation.listing_id = listing.id
    conversation.deal_id = deal.id  # legacy current-deal pointer retained for older clients
    deal.conversation_id = conversation.id
    if unhide_both:
        conversation.buyer_hidden_at = None
        conversation.seller_hidden_at = None
    if created and add_context_if_created:
        conversation.last_message_at = datetime.now(UTC)
        session.add(
            ConversationMessage(
                conversation_id=conversation.id,
                sender_id=deal.buyer_id,
                body=f"Покупатель оплатил {deal.price_af_coins} AF Coins. Деньги под защитой до подтверждения получения.",
                message_type="system",
            )
        )
    return conversation


async def get_or_create_deal_conversation(
    session: AsyncSession,
    actor: User,
    deal_id: uuid.UUID,
) -> Conversation:
    async with session.begin():
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if not deal or actor.id not in {deal.buyer_id, deal.seller_id}:
            raise HTTPException(status_code=404, detail="Deal not found")
        listing = await session.get(Listing, deal.listing_id)
        if not listing:
            raise HTTPException(status_code=409, detail="Listing for deal not found")
        conversation = await _ensure_deal_conversation_locked(
            session,
            deal,
            listing,
            unhide_both=False,
        )
        if actor.id == conversation.buyer_id:
            conversation.buyer_hidden_at = None
        else:
            conversation.seller_hidden_at = None
    return conversation


async def send_conversation_message(
    session: AsyncSession, sender: User, conversation_id: uuid.UUID, body: str, client_message_id: uuid.UUID
) -> tuple[ConversationMessage, User, bool]:
    async with session.begin():
        conversation = await session.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
        if not conversation or sender.id not in {conversation.buyer_id, conversation.seller_id}:
            raise HTTPException(status_code=404, detail="Conversation not found")
        existing = await session.scalar(
            select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.sender_id == sender.id,
                ConversationMessage.client_message_id == client_message_id,
            )
        )
        recipient_id = conversation.seller_id if sender.id == conversation.buyer_id else conversation.buyer_id
        recipient = await session.get(User, recipient_id)
        if existing:
            return existing, recipient, False
        message = ConversationMessage(
            conversation_id=conversation.id, sender_id=sender.id, body=body.strip(),
            message_type="text", client_message_id=client_message_id,
        )
        session.add(message)
        conversation.last_message_at = datetime.now(UTC)
        if recipient_id == conversation.buyer_id:
            conversation.buyer_hidden_at = None
        else:
            conversation.seller_hidden_at = None
        await create_notification(
            session,
            recipient_id,
            "conversation_message",
            "Новое сообщение",
            body.strip()[:240],
            {"conversation_id": str(conversation.id), "listing_id": str(conversation.listing_id)},
        )
        await session.flush()
    return message, recipient, True


async def create_price_offer(session: AsyncSession, actor: User, conversation_id: uuid.UUID, amount: Decimal, parent_offer_id: uuid.UUID | None = None) -> tuple[PriceOffer, User]:
    async with session.begin():
        conversation = await session.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
        if not conversation or actor.id not in {conversation.buyer_id, conversation.seller_id}:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if conversation.deal_id:
            deal = await session.get(Deal, conversation.deal_id)
            if deal and deal.status not in {"cancelled"}:
                raise HTTPException(status_code=409, detail="Price cannot be negotiated after purchase")
        if parent_offer_id:
            parent = await session.scalar(select(PriceOffer).where(PriceOffer.id == parent_offer_id).with_for_update())
            if not parent or parent.conversation_id != conversation.id or parent.status != "pending" or parent.offered_by_id == actor.id:
                raise HTTPException(status_code=409, detail="Counter-offer is not allowed")
            parent.status = "countered"
            parent.responded_at = datetime.now(UTC)
        offer = PriceOffer(
            conversation_id=conversation.id,
            offered_by_id=actor.id,
            amount_af_coins=money(amount),
            status="pending",
            parent_offer_id=parent_offer_id,
        )
        session.add(offer)
        await session.flush()
        conversation.last_message_at = datetime.now(UTC)
        session.add(
            ConversationMessage(
                conversation_id=conversation.id,
                sender_id=actor.id,
                body=f"Предложена цена {offer.amount_af_coins} AF Coins",
                message_type="offer",
            )
        )
        recipient_id = conversation.seller_id if actor.id == conversation.buyer_id else conversation.buyer_id
        await create_notification(session, recipient_id, "price_offer", "Новое предложение цены", f"Предложено {offer.amount_af_coins} AF Coins", {"conversation_id": str(conversation.id), "offer_id": str(offer.id)})
        recipient = await session.get(User, recipient_id)
    return offer, recipient


async def respond_price_offer(session: AsyncSession, actor: User, offer_id: uuid.UUID, accept: bool) -> tuple[PriceOffer, User]:
    async with session.begin():
        offer = await session.scalar(select(PriceOffer).where(PriceOffer.id == offer_id).with_for_update())
        if not offer or offer.status != "pending":
            raise HTTPException(status_code=404, detail="Pending offer not found")
        conversation = await session.scalar(select(Conversation).where(Conversation.id == offer.conversation_id).with_for_update())
        if not conversation or actor.id not in {conversation.buyer_id, conversation.seller_id} or actor.id == offer.offered_by_id:
            raise HTTPException(status_code=403, detail="Only the other participant can respond")
        offer.status = "accepted" if accept else "rejected"
        offer.responded_at = datetime.now(UTC)
        if accept:
            conversation.accepted_price_af_coins = offer.amount_af_coins
        conversation.last_message_at = datetime.now(UTC)
        session.add(
            ConversationMessage(
                conversation_id=conversation.id,
                sender_id=actor.id,
                body="Предложение принято" if accept else "Предложение отклонено",
                message_type="system",
            )
        )
        recipient = await session.get(User, offer.offered_by_id)
        await create_notification(session, offer.offered_by_id, "price_offer_response", "Ответ на предложение цены", "Предложение принято" if accept else "Предложение отклонено", {"conversation_id": str(conversation.id), "offer_id": str(offer.id)})
    return offer, recipient


async def checkout_cart(session: AsyncSession, buyer: User) -> tuple[list[Deal], list[int]]:
    seller_telegram_ids: list[int] = []
    async with session.begin():
        cart_items = list(
            (await session.scalars(select(CartItem).where(CartItem.user_id == buyer.id).with_for_update())).all()
        )
        if not cart_items:
            raise HTTPException(status_code=400, detail="Cart is empty")
        listing_ids = [item.listing_id for item in cart_items]
        listings = list(
            (await session.scalars(select(Listing).where(Listing.id.in_(listing_ids)).with_for_update())).all()
        )
        by_id = {item.id: item for item in listings}
        ordered = [by_id[item_id] for item_id in listing_ids if item_id in by_id]
        if len(ordered) != len(listing_ids) or any(item.status != "active" for item in ordered):
            raise HTTPException(status_code=409, detail="One or more items have already been sold")
        if any(item.seller_id == buyer.id for item in ordered):
            raise HTTPException(status_code=400, detail="You cannot buy your own listing")

        conversations = list(
            (
                await session.scalars(
                    select(Conversation)
                    .where(
                        or_(
                            and_(Conversation.buyer_id == buyer.id, Conversation.seller_id.in_([item.seller_id for item in ordered])),
                            and_(Conversation.seller_id == buyer.id, Conversation.buyer_id.in_([item.seller_id for item in ordered])),
                        )
                    )
                    .with_for_update()
                )
            ).all()
        )
        conversations_by_seller = {
            (item.seller_id if item.buyer_id == buyer.id else item.buyer_id): item
            for item in conversations
        }
        conversations_by_listing = {item.id: conversations_by_seller.get(item.seller_id) for item in ordered}
        effective_prices = {
            item.id: money(conversations_by_listing[item.id].accepted_price_af_coins)
            if conversations_by_listing.get(item.id)
            and conversations_by_listing[item.id].listing_id == item.id
            and conversations_by_listing[item.id].accepted_price_af_coins is not None
            else money(item.price_af_coins)
            for item in ordered
        }
        total = money(sum((effective_prices[item.id] for item in ordered), Decimal("0")))
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id).with_for_update())
        if not wallet or wallet.available_balance < total:
            missing = total if not wallet else money(total - wallet.available_balance)
            raise HTTPException(status_code=402, detail=f"Не хватает {missing} AF Coins")
        available_before, frozen_before = wallet_snapshot(wallet)
        wallet.version += 1

        deals: list[Deal] = []
        for listing in ordered:
            agreed_price = effective_prices[listing.id]
            purchased_part, earned_part = hold_for_purchase(wallet, agreed_price)
            payout, commission = settlement_amounts(agreed_price)
            deal = Deal(
                listing_id=listing.id,
                buyer_id=buyer.id,
                seller_id=listing.seller_id,
                status="paid",
                price_af_coins=agreed_price,
                frozen_amount=agreed_price,
                purchased_frozen_amount=purchased_part,
                earned_frozen_amount=earned_part,
                seller_payout=payout,
                platform_commission=commission,
            )
            session.add(deal)
            await session.flush()
            conversation = conversations_by_listing.get(listing.id)
            if not conversation:
                conversation = Conversation(listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id)
                session.add(conversation)
                await session.flush()
                conversations_by_listing[listing.id] = conversation
            else:
                conversation.listing_id = listing.id
                conversation.accepted_price_af_coins = None
            conversation.deal_id = deal.id
            deal.conversation_id = conversation.id
            conversation.buyer_hidden_at = None
            conversation.seller_hidden_at = None
            conversation.last_message_at = datetime.now(UTC)
            session.add(
                ConversationMessage(
                    conversation_id=conversation.id,
                    sender_id=buyer.id,
                    body=f"Покупатель оплатил {agreed_price} AF Coins. Деньги под защитой до подтверждения получения.",
                    message_type="system",
                )
            )
            listing.status = "reserved"
            listing.reserved_by_deal_id = deal.id
            deals.append(deal)
            seller = await session.get(User, listing.seller_id)
            if seller:
                seller_telegram_ids.append(seller.telegram_id)
                await create_notification(
                    session,
                    seller.id,
                    "deal_created",
                    "Ваш товар хотят купить",
                    "Откройте AUTOFLOW MARKET, чтобы ответить покупателю",
                    {"deal_id": str(deal.id)},
                )

        session.add(
            wallet_transaction(
                wallet,
                "protection_hold",
                -total,
                available_before,
                frozen_before,
                "Деньги переведены под защиту для покупки",
            )
        )
        await session.execute(delete(CartItem).where(CartItem.user_id == buyer.id))
    return deals, seller_telegram_ids


async def _effective_listing_price(session: AsyncSession, buyer: User, listing: Listing) -> tuple[Decimal, Conversation | None]:
    conversation = await session.scalar(
        select(Conversation)
        .where(
            or_(
                and_(Conversation.buyer_id == buyer.id, Conversation.seller_id == listing.seller_id),
                and_(Conversation.buyer_id == listing.seller_id, Conversation.seller_id == buyer.id),
            )
        )
        .with_for_update()
    )
    price = money(listing.price_af_coins)
    if conversation and conversation.listing_id == listing.id and conversation.accepted_price_af_coins is not None:
        price = money(conversation.accepted_price_af_coins)
    return price, conversation


async def _purchase_locked_listing(
    session: AsyncSession,
    buyer: User,
    listing: Listing,
) -> tuple[Deal, int | None]:
    if listing.seller_id == buyer.id:
        raise HTTPException(status_code=400, detail="Нельзя купить собственное объявление")
    if listing.status != "active" or listing.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Объявление уже недоступно")

    agreed_price, conversation = await _effective_listing_price(session, buyer, listing)
    wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id).with_for_update())
    available = wallet.available_balance if wallet else Decimal("0")
    if not wallet or available < agreed_price:
        missing = money(agreed_price - available)
        raise HTTPException(
            status_code=402,
            detail={
                "code": "insufficient_af_coins",
                "missing_af_coins": str(missing),
                "price_af_coins": str(agreed_price),
                "available_af_coins": str(money(available)),
                "listing_id": str(listing.id),
            },
        )

    available_before, frozen_before = wallet_snapshot(wallet)
    purchased_part, earned_part = hold_for_purchase(wallet, agreed_price)
    wallet.version += 1
    payout, commission = settlement_amounts(agreed_price)
    deal = Deal(
        listing_id=listing.id,
        buyer_id=buyer.id,
        seller_id=listing.seller_id,
        status="paid",
        price_af_coins=agreed_price,
        frozen_amount=agreed_price,
        purchased_frozen_amount=purchased_part,
        earned_frozen_amount=earned_part,
        seller_payout=payout,
        platform_commission=commission,
    )
    session.add(deal)
    await session.flush()
    if not conversation:
        conversation = Conversation(listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id)
        session.add(conversation)
        await session.flush()
    else:
        conversation.listing_id = listing.id
        conversation.accepted_price_af_coins = None
    conversation.deal_id = deal.id
    deal.conversation_id = conversation.id
    conversation.buyer_hidden_at = None
    conversation.seller_hidden_at = None
    conversation.last_message_at = datetime.now(UTC)
    session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            sender_id=buyer.id,
            body=f"Покупатель оплатил {agreed_price} AF Coins. Деньги под защитой до подтверждения получения.",
            message_type="system",
        )
    )
    listing.status = "reserved"
    listing.reserved_by_deal_id = deal.id
    session.add(
        wallet_transaction(
            wallet,
            "protection_hold",
            -agreed_price,
            available_before,
            frozen_before,
            "Деньги переведены под защиту для покупки",
            deal_id=deal.id,
            external_reference=f"deal:{deal.id}:protection_hold",
        )
    )
    seller = await session.get(User, listing.seller_id)
    if seller:
        await create_notification(
            session,
            seller.id,
            "deal_created",
            "Ваш товар хотят купить",
            "Покупатель оплатил. Откройте AUTOFLOW MARKET, чтобы продолжить сделку",
            {"deal_id": str(deal.id)},
        )
    return deal, seller.telegram_id if seller and seller.bot_started else None


async def purchase_listing(session: AsyncSession, buyer: User, listing_id: uuid.UUID) -> tuple[Deal, int | None, bool]:
    async with session.begin():
        listing = await session.scalar(select(Listing).where(Listing.id == listing_id).with_for_update())
        if not listing:
            raise HTTPException(status_code=404, detail="Объявление не найдено")
        if listing.seller_id == buyer.id:
            raise HTTPException(status_code=400, detail="Нельзя купить собственное объявление")
        if listing.status == "reserved" and listing.reserved_by_deal_id:
            existing = await session.scalar(select(Deal).where(Deal.id == listing.reserved_by_deal_id).with_for_update())
            if existing and existing.buyer_id == buyer.id and existing.status not in {"completed", "cancelled"}:
                await _ensure_deal_conversation_locked(session, existing, listing, unhide_both=True)
                seller = await session.get(User, existing.seller_id)
                return existing, seller.telegram_id if seller and seller.bot_started else None, False
        deal, seller_telegram_id = await _purchase_locked_listing(session, buyer, listing)
    return deal, seller_telegram_id, True


async def create_listing_payment_intent(
    session: AsyncSession,
    user: User,
    listing_id: uuid.UUID,
    invoice_factory: Callable[[int, str], Awaitable[str]],
) -> StarPaymentIntent:
    now = datetime.now(UTC)
    async with session.begin():
        listing = await session.scalar(select(Listing).where(Listing.id == listing_id).with_for_update())
        if not listing or listing.status != "active" or listing.deleted_at is not None:
            raise HTTPException(status_code=409, detail="Объявление уже недоступно")
        if listing.seller_id == user.id:
            raise HTTPException(status_code=400, detail="Нельзя купить собственное объявление")
        existing = await session.scalar(
            select(StarPaymentIntent)
            .where(
                StarPaymentIntent.user_id == user.id,
                StarPaymentIntent.listing_id == listing.id,
                StarPaymentIntent.purpose == "listing_checkout",
                StarPaymentIntent.status == "pending",
            )
            .with_for_update()
        )
        if existing and existing.expires_at > now:
            if existing.invoice_link:
                return existing
            raise HTTPException(status_code=409, detail="Счёт уже создаётся. Повторите через несколько секунд")
        if existing:
            existing.status = "expired"
        price, _conversation = await _effective_listing_price(session, user, listing)
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id).with_for_update())
        available = money(wallet.available_balance if wallet else Decimal("0"))
        missing = money(price - available)
        if missing <= 0:
            raise HTTPException(status_code=409, detail="Средств уже достаточно. Нажмите «Оплатить безопасно» ещё раз")
        xtr_amount = int(missing.to_integral_value(rounding=ROUND_CEILING))
        intent_id = uuid.uuid4()
        intent = StarPaymentIntent(
            id=intent_id,
            user_id=user.id,
            invoice_payload=f"autoflow_topup:{intent_id}",
            xtr_amount=xtr_amount,
            purpose="listing_checkout",
            context={"listing_title": " ".join(filter(None, [listing.brand, listing.model]))},
            listing_id=listing.id,
            seller_id=listing.seller_id,
            listing_price_af_coins=price,
            available_balance_at_creation=available,
            missing_af_coins=missing,
            checkout_status="pending",
            status="pending",
            expires_at=now + timedelta(minutes=30),
        )
        session.add(intent)

    try:
        invoice_link = await invoice_factory(intent.xtr_amount, intent.invoice_payload)
    except Exception:
        async with session.begin():
            locked = await session.scalar(select(StarPaymentIntent).where(StarPaymentIntent.id == intent.id).with_for_update())
            if locked and locked.status == "pending":
                locked.status = "cancelled"
                locked.checkout_status = "failed"
        raise
    async with session.begin():
        locked = await session.scalar(select(StarPaymentIntent).where(StarPaymentIntent.id == intent.id).with_for_update())
        if not locked or locked.status != "pending":
            raise HTTPException(status_code=409, detail="Счёт больше недоступен")
        locked.invoice_link = invoice_link
    return locked


async def complete_listing_payment_intent(
    session: AsyncSession,
    user: User,
    intent_id: uuid.UUID,
) -> tuple[StarPaymentIntent, Deal | None, int | None]:
    async with session.begin():
        intent = await session.scalar(select(StarPaymentIntent).where(StarPaymentIntent.id == intent_id).with_for_update())
        if not intent or intent.user_id != user.id or intent.purpose != "listing_checkout":
            raise HTTPException(status_code=404, detail="Счёт покупки не найден")
        if intent.status != "paid":
            raise HTTPException(status_code=409, detail="Telegram ещё не подтвердил оплату")
        if intent.checkout_status == "completed" and intent.deal_id:
            return intent, await session.get(Deal, intent.deal_id), None
        if intent.checkout_status in {"listing_unavailable", "failed"}:
            return intent, None, None
        listing = await session.scalar(select(Listing).where(Listing.id == intent.listing_id).with_for_update())
        if not listing or listing.status != "active" or listing.deleted_at is not None:
            intent.checkout_status = "listing_unavailable"
            await create_notification(
                session,
                user.id,
                "listing_checkout_unavailable",
                "Объявление уже недоступно",
                "Пополненные AF Coins сохранены на вашем балансе.",
                {"intent_id": str(intent.id), "listing_id": str(intent.listing_id)},
            )
            return intent, None, None
        current_price, _conversation = await _effective_listing_price(session, user, listing)
        if listing.seller_id != intent.seller_id or current_price != money(intent.listing_price_af_coins):
            intent.checkout_status = "failed"
            await create_notification(
                session,
                user.id,
                "listing_checkout_changed",
                "Условия объявления изменились",
                "Пополненные AF Coins сохранены на вашем балансе.",
                {"intent_id": str(intent.id), "listing_id": str(intent.listing_id)},
            )
            return intent, None, None
        try:
            deal, seller_telegram_id = await _purchase_locked_listing(session, user, listing)
        except HTTPException as error:
            if error.status_code != 402:
                raise
            intent.checkout_status = "failed"
            await create_notification(
                session,
                user.id,
                "listing_checkout_failed",
                "Покупка не завершена автоматически",
                "Пополненные AF Coins сохранены на вашем балансе.",
                {"intent_id": str(intent.id), "listing_id": str(intent.listing_id)},
            )
            return intent, None, None
        intent.deal_id = deal.id
        intent.checkout_status = "completed"
    return intent, deal, seller_telegram_id


async def set_deal_status(session: AsyncSession, actor: User, deal_id: uuid.UUID, next_status: str) -> Deal:
    allowed = {
        "seller_contacted": {"paid"},
        "transfer_in_progress": {"paid", "seller_contacted"},
        "disputed": {"paid", "seller_contacted", "transfer_in_progress"},
    }
    async with session.begin():
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if not deal or actor.id not in {deal.buyer_id, deal.seller_id}:
            raise HTTPException(status_code=404, detail="Deal not found")
        if deal.status not in allowed[next_status]:
            raise HTTPException(status_code=409, detail=f"Cannot change {deal.status} to {next_status}")
        if next_status in {"seller_contacted", "transfer_in_progress"} and actor.id != deal.seller_id:
            raise HTTPException(status_code=403, detail="Only the seller can change this status")
        deal.status = next_status
        if next_status == "transfer_in_progress":
            deal.transfer_started_at = datetime.now(UTC)
        other_id = deal.seller_id if actor.id == deal.buyer_id else deal.buyer_id
        await create_notification(session, other_id, "deal_status", "Статус сделки изменён", f"Новый статус: {next_status}", {"deal_id": str(deal.id)})
    return deal


async def create_deal_support_case(
    session: AsyncSession,
    author: User,
    deal_id: uuid.UUID,
    message: str,
    client_request_id: uuid.UUID,
) -> tuple[SupportTicket, Listing, User, User, list[User]]:
    """Open (or reuse) one active support case and freeze the deal for review."""
    async with session.begin():
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if not deal or author.id not in {deal.buyer_id, deal.seller_id}:
            raise HTTPException(status_code=404, detail="Сделка не найдена")
        if deal.status in {"completed", "cancelled", "pending_payment"}:
            raise HTTPException(status_code=409, detail="Для этой сделки обращение сейчас недоступно")
        listing = await session.get(Listing, deal.listing_id)
        buyer = await session.get(User, deal.buyer_id)
        seller = await session.get(User, deal.seller_id)
        if not listing or not buyer or not seller:
            raise HTTPException(status_code=409, detail="Контекст сделки повреждён")
        ticket = await session.scalar(
            select(SupportTicket).where(
                SupportTicket.deal_id == deal.id,
                SupportTicket.status.in_({"new", "open", "in_progress"}),
            ).with_for_update()
        )
        created = ticket is None
        if ticket:
            existing_message = await session.scalar(select(SupportMessage).where(
                SupportMessage.ticket_id == ticket.id,
                SupportMessage.sender_id == author.id,
                SupportMessage.client_request_id == client_request_id,
            ))
            if existing_message:
                return ticket, listing, buyer, seller, []
        if created:
            ticket = SupportTicket(
                user_id=author.id,
                author_id=author.id,
                case_type="deal",
                deal_id=deal.id,
                listing_id=listing.id,
                buyer_id=deal.buyer_id,
                seller_id=deal.seller_id,
                topic="Проблема по сделке",
                status="new",
                unread_by_admin=True,
            )
            session.add(ticket)
            await session.flush()
            session.add(SupportCaseEvent(
                ticket_id=ticket.id,
                actor_id=author.id,
                event_type="case_created",
                to_status="new",
                details={"deal_id": str(deal.id)},
            ))
        ticket.unread_by_admin = True
        session.add(SupportMessage(
            ticket_id=ticket.id,
            sender_id=author.id,
            client_request_id=client_request_id,
            body=message.strip(),
        ))
        session.add(SupportCaseEvent(
            ticket_id=ticket.id,
            actor_id=author.id,
            event_type="participant_message",
            details={"created_with_case": created},
        ))
        if deal.status != "disputed":
            deal.status = "disputed"
        administrators = list((await session.scalars(select(User).where(User.role == "admin"))).all())
        for administrator in administrators:
            await create_notification(
                session,
                administrator.id,
                "deal_support_case",
                "Новое обращение по сделке",
                f"{listing.brand} {listing.model}".strip(),
                {"ticket_id": str(ticket.id), "deal_id": str(deal.id)},
            )
    return ticket, listing, buyer, seller, administrators


async def complete_deal(session: AsyncSession, buyer: User, deal_id: uuid.UUID) -> Deal:
    async with session.begin():
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if not deal or deal.buyer_id != buyer.id:
            raise HTTPException(status_code=404, detail="Deal not found")
        if deal.status != "transfer_in_progress" or not deal.transfer_started_at:
            raise HTTPException(status_code=409, detail="Transfer has not started")
        if datetime.now(UTC) - deal.transfer_started_at < timedelta(seconds=60):
            raise HTTPException(status_code=409, detail="Подтверждение станет доступно через 60 секунд после начала передачи")
        listing = await session.scalar(select(Listing).where(Listing.id == deal.listing_id).with_for_update())
        buyer_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == deal.buyer_id).with_for_update())
        seller_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == deal.seller_id).with_for_update())
        if not listing or not buyer_wallet or not seller_wallet:
            raise HTTPException(status_code=409, detail="Settlement state is inconsistent")

        buyer_avail_before, buyer_frozen_before = buyer_wallet.available_balance, buyer_wallet.frozen_balance
        seller_avail_before, seller_frozen_before = seller_wallet.available_balance, seller_wallet.frozen_balance
        consume_purchase_hold(buyer_wallet, deal.purchased_frozen_amount, deal.earned_frozen_amount)
        buyer_wallet.version += 1
        seller_wallet.earned_balance = money(seller_wallet.earned_balance + deal.seller_payout)
        seller_wallet.total_earned = money(seller_wallet.total_earned + deal.seller_payout)
        seller_wallet.version += 1

        now = datetime.now(UTC)
        deal.status = "completed"
        deal.buyer_confirmed_at = now
        deal.completed_at = now
        listing.status = "sold"
        listing.sold_at = now
        listing.reserved_by_deal_id = None
        session.add(wallet_transaction(buyer_wallet, "purchase_completed", Decimal("0"), buyer_avail_before, buyer_frozen_before, "Покупка завершена", deal_id=deal.id))
        session.add(wallet_transaction(seller_wallet, "sale_income", deal.seller_payout, seller_avail_before, seller_frozen_before, f"{get_settings().seller_payout_percent}% стоимости сделки начислено продавцу", deal_id=deal.id))
        session.add(wallet_transaction(buyer_wallet, "platform_commission", -deal.platform_commission, buyer_wallet.available_balance, buyer_wallet.frozen_balance, f"Комиссия платформы {100 - get_settings().seller_payout_percent}%", deal_id=deal.id))
        await create_notification(session, deal.seller_id, "deal_completed", "Сделка завершена", f"Начислено {deal.seller_payout} AF Coins", {"deal_id": str(deal.id)})
    return deal


async def cancel_deal(session: AsyncSession, actor: User, deal_id: uuid.UUID) -> Deal:
    """Cancel an unstarted transfer and atomically release the buyer's reservation."""
    async with session.begin():
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if not deal or actor.id not in {deal.buyer_id, deal.seller_id}:
            raise HTTPException(status_code=404, detail="Deal not found")
        if deal.status not in {"paid", "seller_contacted"}:
            raise HTTPException(status_code=409, detail="This deal can no longer be cancelled automatically")

        listing = await session.scalar(select(Listing).where(Listing.id == deal.listing_id).with_for_update())
        buyer_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == deal.buyer_id).with_for_update())
        if not listing or not buyer_wallet:
            raise HTTPException(status_code=409, detail="Cancellation state is inconsistent")

        available_before, frozen_before = buyer_wallet.available_balance, buyer_wallet.frozen_balance
        release_purchase_hold(buyer_wallet, deal.purchased_frozen_amount, deal.earned_frozen_amount)
        buyer_wallet.version += 1
        deal.status = "cancelled"
        deal.cancelled_at = datetime.now(UTC)
        listing.status = "active"
        listing.reserved_by_deal_id = None
        session.add(
            wallet_transaction(
                buyer_wallet,
                "refund",
                deal.frozen_amount,
                available_before,
                frozen_before,
                "Защищённые средства возвращены после отмены сделки",
                deal_id=deal.id,
            )
        )
        other_id = deal.seller_id if actor.id == deal.buyer_id else deal.buyer_id
        await create_notification(
            session,
            other_id,
            "deal_cancelled",
            "Сделка отменена",
            "Защищённые средства возвращены покупателю",
            {"deal_id": str(deal.id)},
        )
    return deal


async def resolve_dispute(
    session: AsyncSession,
    admin: User,
    deal_id: uuid.UUID,
    outcome: str,
    reason: str,
    *,
    support_ticket_id: uuid.UUID | None = None,
) -> Deal:
    async with session.begin():
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if not deal or deal.status != "disputed":
            raise HTTPException(status_code=404, detail="Disputed deal not found")
        listing = await session.scalar(select(Listing).where(Listing.id == deal.listing_id).with_for_update())
        buyer_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == deal.buyer_id).with_for_update())
        seller_wallet = await session.scalar(select(Wallet).where(Wallet.user_id == deal.seller_id).with_for_update())
        if not listing or not buyer_wallet or not seller_wallet:
            raise HTTPException(status_code=409, detail="Settlement state is inconsistent")
        buyer_available_before, buyer_frozen_before = buyer_wallet.available_balance, buyer_wallet.frozen_balance
        now = datetime.now(UTC)
        support_ticket = None
        if support_ticket_id:
            support_ticket = await session.scalar(
                select(SupportTicket).where(SupportTicket.id == support_ticket_id).with_for_update()
            )
            if not support_ticket or support_ticket.deal_id != deal.id:
                raise HTTPException(status_code=404, detail="Обращение по сделке не найдено")
            if support_ticket.status in {"resolved", "closed"}:
                raise HTTPException(status_code=409, detail="Обращение уже решено")
        if outcome == "refund":
            release_purchase_hold(buyer_wallet, deal.purchased_frozen_amount, deal.earned_frozen_amount)
            buyer_wallet.version += 1
            deal.status = "cancelled"
            deal.cancelled_at = now
            listing.status = "active"
            listing.reserved_by_deal_id = None
            session.add(wallet_transaction(buyer_wallet, "dispute_refund", deal.frozen_amount, buyer_available_before, buyer_frozen_before, f"Возврат по спору: {reason}", deal_id=deal.id))
            buyer_body = "Средства возвращены на доступный баланс"
            seller_body = "Сделка отменена, средства возвращены покупателю"
        else:
            seller_available_before, seller_frozen_before = seller_wallet.available_balance, seller_wallet.frozen_balance
            consume_purchase_hold(buyer_wallet, deal.purchased_frozen_amount, deal.earned_frozen_amount)
            buyer_wallet.version += 1
            seller_wallet.earned_balance = money(seller_wallet.earned_balance + deal.seller_payout)
            seller_wallet.total_earned = money(seller_wallet.total_earned + deal.seller_payout)
            seller_wallet.version += 1
            deal.status = "completed"
            deal.completed_at = now
            listing.status = "sold"
            listing.sold_at = now
            listing.reserved_by_deal_id = None
            session.add(wallet_transaction(buyer_wallet, "dispute_completed", Decimal("0"), buyer_available_before, buyer_frozen_before, f"Сделка завершена администратором: {reason}", deal_id=deal.id))
            session.add(wallet_transaction(seller_wallet, "sale_income", deal.seller_payout, seller_available_before, seller_frozen_before, f"{get_settings().seller_payout_percent}% начислено после решения спора: {reason}", deal_id=deal.id))
            session.add(wallet_transaction(buyer_wallet, "platform_commission", -deal.platform_commission, buyer_wallet.available_balance, buyer_wallet.frozen_balance, f"Комиссия платформы {100 - get_settings().seller_payout_percent}% после решения спора", deal_id=deal.id))
            buyer_body = "Сделка завершена решением администратора"
            seller_body = f"Сделка завершена, начислено {deal.seller_payout} AF Coins"
        session.add(AdminAction(admin_id=admin.id, action=f"resolve_dispute_{outcome}", target_type="deal", target_id=deal.id, reason=reason))
        if support_ticket:
            previous_status = support_ticket.status
            support_ticket.status = "resolved"
            support_ticket.resolved_at = now
            support_ticket.unread_by_admin = False
            session.add(SupportCaseEvent(
                ticket_id=support_ticket.id,
                actor_id=admin.id,
                event_type=f"financial_resolution_{outcome}",
                from_status=previous_status,
                to_status="resolved",
                details={"reason": reason, "deal_id": str(deal.id), "amount": str(deal.frozen_amount)},
            ))
            session.add(AdminAction(
                admin_id=admin.id,
                action=f"resolve_support_case_{outcome}",
                target_type="support_ticket",
                target_id=support_ticket.id,
                reason=reason,
                metadata_json={"deal_id": str(deal.id), "amount": str(deal.frozen_amount)},
            ))
        await create_notification(session, deal.buyer_id, "dispute_resolved", "Спор рассмотрен", buyer_body, {"deal_id": str(deal.id)})
        await create_notification(session, deal.seller_id, "dispute_resolved", "Спор рассмотрен", seller_body, {"deal_id": str(deal.id)})
    return deal


async def create_withdrawal(session: AsyncSession, user: User, payload) -> WithdrawalRequest:
    minimum = money(get_settings().min_withdrawal_af_coins)
    amount = money(payload.amount)
    if amount < minimum:
        raise HTTPException(status_code=400, detail=f"Minimum withdrawal is {minimum} AF Coins")
    async with session.begin():
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id).with_for_update())
        if not wallet or wallet.earned_balance < amount:
            raise HTTPException(status_code=402, detail="Для вывода доступны только AF Coins, заработанные с продаж")
        before_available, before_frozen = wallet_snapshot(wallet)
        wallet.earned_balance = money(wallet.earned_balance - amount)
        wallet.earned_frozen_balance = money(wallet.earned_frozen_balance + amount)
        wallet.version += 1
        withdrawal = WithdrawalRequest(user_id=user.id, amount=amount, payout_method=payload.payout_method, details=payload.details, status="pending")
        session.add(withdrawal)
        await session.flush()
        session.add(wallet_transaction(wallet, "withdrawal_reserved", -amount, before_available, before_frozen, "AF Coins заморожены для заявки на вывод", withdrawal_id=withdrawal.id))
        admins = list((await session.scalars(select(User).where(User.role == "admin"))).all())
        for admin in admins:
            await create_notification(session, admin.id, "withdrawal_created", "Новая заявка на вывод", f"Пользователь {user.telegram_id}: {amount} AF Coins", {"withdrawal_id": str(withdrawal.id)})
    return withdrawal


async def decide_withdrawal(session: AsyncSession, admin: User, withdrawal_id: uuid.UUID, action: str, reason: str | None) -> WithdrawalRequest:
    targets = {"approve": "approved", "paid": "paid", "reject": "rejected"}
    expected = {"approve": {"pending"}, "paid": {"approved"}, "reject": {"pending", "approved"}}[action]
    target = targets[action]
    async with session.begin():
        request = await session.scalar(select(WithdrawalRequest).where(WithdrawalRequest.id == withdrawal_id).with_for_update())
        if not request:
            raise HTTPException(status_code=404, detail="Withdrawal not found")
        if request.status not in expected:
            raise HTTPException(status_code=409, detail=f"Withdrawal must be one of {sorted(expected)}")
        if action == "reject" and not reason:
            raise HTTPException(status_code=400, detail="Rejection reason is required")
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == request.user_id).with_for_update())
        if not wallet:
            raise HTTPException(status_code=409, detail="Wallet not found")
        before_available, before_frozen = wallet.available_balance, wallet.frozen_balance
        now = datetime.now(UTC)
        request.status = target
        request.reviewed_by_id = admin.id
        request.reviewed_at = now
        transaction = None
        if action == "paid":
            if wallet.earned_frozen_balance < request.amount:
                raise HTTPException(status_code=409, detail="Frozen balance is insufficient")
            wallet.earned_frozen_balance = money(wallet.earned_frozen_balance - request.amount)
            request.paid_at = now
            transaction = wallet_transaction(wallet, "withdrawal_paid", -request.amount, before_available, before_frozen, "Ручная выплата отмечена администратором", withdrawal_id=request.id)
        elif action == "reject":
            if wallet.earned_frozen_balance < request.amount:
                raise HTTPException(status_code=409, detail="Frozen balance is insufficient")
            wallet.earned_frozen_balance = money(wallet.earned_frozen_balance - request.amount)
            wallet.earned_balance = money(wallet.earned_balance + request.amount)
            request.rejection_reason = reason
            transaction = wallet_transaction(wallet, "withdrawal_rejected", request.amount, before_available, before_frozen, f"Заявка отклонена: {reason}", withdrawal_id=request.id)
        wallet.version += 1
        if transaction:
            session.add(transaction)
        session.add(AdminAction(admin_id=admin.id, action=f"withdrawal_{target}", target_type="withdrawal", target_id=request.id, reason=reason))
        await create_notification(session, request.user_id, f"withdrawal_{target}", "Статус заявки на вывод изменён", f"Новый статус: {target}", {"withdrawal_id": str(request.id)})
    return request


async def cancel_withdrawal(session: AsyncSession, user: User, withdrawal_id: uuid.UUID) -> WithdrawalRequest:
    async with session.begin():
        request = await session.scalar(
            select(WithdrawalRequest).where(WithdrawalRequest.id == withdrawal_id).with_for_update()
        )
        if not request or request.user_id != user.id:
            raise HTTPException(status_code=404, detail="Withdrawal not found")
        if request.status != "pending":
            raise HTTPException(status_code=409, detail="Only a pending withdrawal can be cancelled")
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id).with_for_update())
        if not wallet or wallet.earned_frozen_balance < request.amount:
            raise HTTPException(status_code=409, detail="Withdrawal state is inconsistent")
        before_available, before_frozen = wallet.available_balance, wallet.frozen_balance
        wallet.earned_balance = money(wallet.earned_balance + request.amount)
        wallet.earned_frozen_balance = money(wallet.earned_frozen_balance - request.amount)
        wallet.version += 1
        request.status = "cancelled"
        session.add(
            wallet_transaction(
                wallet,
                "withdrawal_cancelled",
                request.amount,
                before_available,
                before_frozen,
                "Заявка отменена пользователем, AF Coins возвращены",
                withdrawal_id=request.id,
            )
        )
    return request


async def adjust_balance(session: AsyncSession, admin: User, payload) -> Wallet:
    amount = money(payload.amount)
    async with session.begin():
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == payload.user_id).with_for_update())
        if not wallet:
            raise HTTPException(status_code=404, detail="Wallet not found")
        before_available, before_frozen = wallet.available_balance, wallet.frozen_balance
        if wallet.available_balance + amount < 0:
            raise HTTPException(status_code=409, detail="Adjustment would make balance negative")
        if amount >= 0:
            wallet.purchased_balance = money(wallet.purchased_balance + amount)
        else:
            debit_spendable(wallet, -amount)
        wallet.version += 1
        transaction = wallet_transaction(wallet, "admin_adjustment", amount, before_available, before_frozen, payload.reason)
        session.add(transaction)
        await session.flush()
        session.add(AdminBalanceAdjustment(admin_id=admin.id, user_id=payload.user_id, amount=amount, reason=payload.reason, wallet_transaction_id=transaction.id))
        session.add(AdminAction(admin_id=admin.id, action="balance_adjustment", target_type="user", target_id=payload.user_id, reason=payload.reason, metadata_json={"amount": str(amount)}))
    return wallet


async def create_star_payment_intent(
    session: AsyncSession,
    user: User,
    amount: int,
    invoice_factory: Callable[[int, str], Awaitable[str]],
    purpose: str = "topup",
) -> StarPaymentIntent:
    settings = get_settings()
    context: dict = {}
    if purpose == "cart_checkout":
        cart_listing_ids = list((await session.scalars(select(CartItem.listing_id).where(CartItem.user_id == user.id))).all())
        if not cart_listing_ids:
            raise HTTPException(status_code=400, detail="Корзина пуста")
        listings = list((await session.scalars(select(Listing).where(Listing.id.in_(cart_listing_ids), Listing.status == "active"))).all())
        if len(listings) != len(cart_listing_ids):
            raise HTTPException(status_code=409, detail="Один из товаров уже недоступен")
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
        total = money(sum((money(item.price_af_coins) for item in listings), Decimal("0")))
        missing = money(total - (wallet.available_balance if wallet else Decimal("0")))
        if missing <= 0:
            raise HTTPException(status_code=409, detail="Средств уже достаточно, повторите покупку")
        amount = max(settings.star_topup_min, int(missing.to_integral_value(rounding=ROUND_CEILING)))
        context = {"listing_ids": [str(item) for item in cart_listing_ids], "required_af_coins": str(missing)}
        await session.commit()
    if amount < settings.star_topup_min or amount > settings.star_topup_max:
        raise HTTPException(
            status_code=400,
            detail=f"Количество Stars должно быть от {settings.star_topup_min} до {settings.star_topup_max}",
        )
    intent_id = uuid.uuid4()
    invoice_payload = f"autoflow_topup:{intent_id}"
    invoice_link = await invoice_factory(amount, invoice_payload)
    intent = StarPaymentIntent(
        id=intent_id,
        user_id=user.id,
        invoice_payload=invoice_payload,
        invoice_link=invoice_link,
        xtr_amount=amount,
        purpose=purpose,
        context=context,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    async with session.begin():
        session.add(intent)
    return intent


async def validate_star_pre_checkout(
    session: AsyncSession,
    telegram_id: int,
    invoice_payload: str,
    currency: str,
    total_amount: int,
) -> tuple[bool, str | None]:
    if currency != "XTR":
        return False, "Поддерживаются только платежи Telegram Stars"
    intent = await session.scalar(select(StarPaymentIntent).where(StarPaymentIntent.invoice_payload == invoice_payload))
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if not intent or not user or intent.user_id != user.id:
        return False, "Счёт не найден или принадлежит другому пользователю"
    if intent.status != "pending":
        return False, "Этот счёт уже обработан"
    if intent.expires_at <= datetime.now(UTC):
        intent.status = "expired"
        await session.commit()
        return False, "Срок действия счёта истёк"
    if intent.xtr_amount != total_amount:
        return False, "Сумма счёта не совпадает"
    return True, None


async def process_successful_payment(session: AsyncSession, telegram_id: int, payment: dict) -> bool:
    if payment.get("currency") != "XTR":
        raise HTTPException(status_code=400, detail="Only XTR top-ups are accepted")
    invoice_payload = str(payment.get("invoice_payload") or "")
    charge_id = str(payment.get("telegram_payment_charge_id") or "")
    xtr_amount = int(payment.get("total_amount") or 0)
    if not invoice_payload.startswith(("autoflow_topup:", "autoflow_training:")) or not charge_id or xtr_amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid successful_payment payload")

    async with session.begin():
        if await session.scalar(select(StarPayment.id).where(StarPayment.telegram_payment_charge_id == charge_id)):
            return False
        intent = await session.scalar(
            select(StarPaymentIntent).where(StarPaymentIntent.invoice_payload == invoice_payload).with_for_update()
        )
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if not intent or not user or intent.user_id != user.id:
            raise HTTPException(status_code=400, detail="Payment intent does not belong to this user")
        if intent.status == "paid":
            return False
        if intent.status != "pending" or intent.xtr_amount != xtr_amount:
            raise HTTPException(status_code=400, detail="Invoice amount or status mismatch")
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id).with_for_update())
        if not wallet:
            raise HTTPException(status_code=409, detail="Wallet not found")

        amount = money(xtr_amount)
        before_available, before_frozen = wallet.available_balance, wallet.frozen_balance
        wallet.purchased_balance = money(wallet.purchased_balance + amount)
        wallet.version += 1
        intent.status = "paid"
        intent.paid_at = datetime.now(UTC)
        session.add(
            StarPayment(
                user_id=user.id,
                telegram_payment_charge_id=charge_id,
                provider_payment_charge_id=payment.get("provider_payment_charge_id"),
                xtr_amount=xtr_amount,
                af_coin_amount=amount,
                status="credited",
                raw_payload=payment,
                processed_at=datetime.now(UTC),
            )
        )
        session.add(
            wallet_transaction(
                wallet,
                "star_payment_credit",
                amount,
                before_available,
                before_frozen,
                "Telegram Stars converted to AF Coins 1:1",
                external_reference=charge_id,
            )
        )
        await create_notification(
            session,
            user.id,
            "wallet_topup",
            "Баланс пополнен",
            f"Начислено {amount} AF Coins",
            {"payment_id": charge_id, "intent_id": str(intent.id)},
        )
    return True
