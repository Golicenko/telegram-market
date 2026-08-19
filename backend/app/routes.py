import hmac
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Query, Response, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user, require_admin
from .broadcasts import create_admin_broadcast, parse_broadcast_command, run_admin_broadcast
from .bot import (
    answer_bot_callback,
    answer_pre_checkout_query,
    create_star_invoice_link,
    create_training_invoice_link,
    send_deal_support_case_notification,
    send_personal_training_order_notification,
    send_bot_notification,
    send_bot_menu,
    send_bot_material,
    upload_bot_material,
)
from .config import Settings, get_settings
from .database import SessionLocal, get_session
from .models import AccountListing, AdminAction, Advertisement, CartItem, Conversation, ConversationMessage, Deal, DealMessage, Favorite, Listing, ListingImage, Notification, PriceOffer, StarPayment, StarPaymentIntent, SupportCaseEvent, SupportMessage, SupportTicket, TrainingMaterial, TrainingProduct, TrainingPurchase, UploadedImage, User, Wallet, WalletTransaction, WithdrawalRequest
from .schemas import (
    AccountListingCreate,
    AccountListingOut,
    AccountListingUpdate,
    AdvertisementOut,
    AdvertisementUpsert,
    AdminWithdrawalOut,
    BalanceAdjustmentCreate,
    ConversationMessageOut,
    ConversationMessageCreate,
    CounterOfferCreate,
    DealResolution,
    DealOut,
    ListingCreate,
    ListingOut,
    ListingUpdate,
    MeOut,
    MessageCreate,
    MessageOut,
    NotificationOut,
    PriceOfferCreate,
    PriceOfferOut,
    ProfileOut,
    StarPaymentIntentCreate,
    StarPaymentIntentOut,
    StarPaymentStatusOut,
    SupportReplyCreate,
    DealSupportCaseCreate,
    SupportCaseEventOut,
    SupportCaseResolution,
    SupportMessageOut,
    SupportStatusUpdate,
    SupportTicketCreate,
    SupportTicketOut,
    TrainingProductCreate,
    TrainingAdminProductOut,
    TrainingAdminStatsOut,
    TrainingBuyerOut,
    TrainingMaterialAdminOut,
    TrainingMaterialCreate,
    TrainingMaterialPublicOut,
    TrainingMaterialUpdate,
    TrainingProductOut,
    TrainingProductUpdate,
    TrainingPurchaseAdminOut,
    TrainingPurchaseOut,
    TrainingPurchaseStatusUpdate,
    UniqueListingCreate,
    UserOut,
    WalletOut,
    WithdrawalCreate,
    WithdrawalDecision,
    WithdrawalOut,
)
from .services import (
    adjust_balance,
    cancel_deal,
    cancel_withdrawal,
    checkout_cart,
    complete_deal,
    create_account_listing,
    create_listing,
    create_notification,
    create_deal_support_case,
    create_price_offer,
    create_star_payment_intent,
    create_training_product,
    create_training_material,
    create_training_payment_intent,
    create_listing_payment_intent,
    create_withdrawal,
    decide_withdrawal,
    delete_account_listing,
    delete_listing,
    delete_special_listing,
    delete_training_product,
    delete_training_material,
    begin_training_delivery,
    finish_training_delivery,
    get_or_create_deal_conversation,
    get_or_create_conversation,
    process_successful_payment,
    purchase_listing,
    complete_listing_payment_intent,
    complete_training_payment_intent,
    promote_listing,
    resolve_dispute,
    respond_price_offer,
    send_conversation_message,
    set_deal_status,
    set_listing_publication,
    update_account_listing,
    update_listing,
    update_special_listing,
    update_training_product,
    update_training_material,
    update_training_purchase_status,
    purchase_training_product,
    set_training_product_state,
    validate_star_pre_checkout,
)


router = APIRouter(prefix="/api")
logger = logging.getLogger("autoflow.training")
register_heif_opener()
Image.MAX_IMAGE_PIXELS = 100_000_000
UPLOAD_DIR = Path(get_settings().upload_dir) if get_settings().upload_dir else Path(__file__).resolve().parents[1] / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def listing_out(session: AsyncSession, listing: Listing, buyer_id: uuid.UUID | None = None) -> ListingOut:
    images = list((await session.scalars(select(ListingImage.url).where(ListingImage.listing_id == listing.id).order_by(ListingImage.position))).all())
    effective_price = None
    if buyer_id:
        effective_price = await session.scalar(
            select(Conversation.accepted_price_af_coins).where(
                Conversation.listing_id == listing.id,
                Conversation.buyer_id == buyer_id,
            )
        )
    is_pinned = bool(listing.pinned and listing.pinned_until and listing.pinned_until > datetime.now(UTC))
    return ListingOut.model_validate(listing).model_copy(
        update={"images": images, "pinned": is_pinned, "effective_price_af_coins": effective_price}
    )


async def expire_promotions(session: AsyncSession) -> None:
    result = await session.execute(
        update(Listing)
        .where(Listing.pinned.is_(True), Listing.pinned_until <= datetime.now(UTC))
        .values(pinned=False, pinned_until=None)
    )
    if result.rowcount:
        await session.commit()


async def conversation_details(
    session: AsyncSession,
    conversation: Conversation,
    viewer: User | None = None,
    allow_admin: bool = False,
    deal_override: Deal | None = None,
) -> dict:
    if viewer and not allow_admin and viewer.id not in {conversation.buyer_id, conversation.seller_id}:
        raise HTTPException(status_code=404, detail="Conversation not found")
    deal = deal_override or await session.scalar(
        select(Deal).where(Deal.conversation_id == conversation.id).order_by(Deal.created_at.desc()).limit(1)
    )
    if not deal and conversation.deal_id:
        deal = await session.get(Deal, conversation.deal_id)
    listing = await session.get(Listing, deal.listing_id if deal else conversation.listing_id)
    other_id = conversation.seller_id if viewer and viewer.id == conversation.buyer_id else conversation.buyer_id
    other = await session.get(User, other_id)
    offers = list((await session.scalars(select(PriceOffer).where(PriceOffer.conversation_id == conversation.id).order_by(PriceOffer.created_at))).all())
    last_message = await session.scalar(
        select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id).order_by(ConversationMessage.created_at.desc()).limit(1)
    )
    unread_count = 0
    if viewer:
        unread_count = int(await session.scalar(
            select(func.count(ConversationMessage.id)).where(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.sender_id != viewer.id,
                ConversationMessage.is_read.is_(False),
            )
        ) or 0)
    return {
        "id": str(conversation.id),
        "listing": await listing_out(session, listing, viewer.id if viewer else None),
        "deal": DealOut.model_validate(deal) if deal else None,
        "buyer_id": str(conversation.buyer_id),
        "seller_id": str(conversation.seller_id),
        "accepted_price_af_coins": conversation.accepted_price_af_coins,
        "counterparty": {
            "id": str(other.id),
            "name": " ".join(filter(None, [other.first_name, other.last_name])),
            "username": other.username,
            "photo_url": other.photo_url,
            "mini_app_last_active_at": other.mini_app_last_active_at,
        },
        "offers": [PriceOfferOut.model_validate(item) for item in offers],
        "created_at": conversation.created_at,
        "last_message_at": conversation.last_message_at,
        "last_message": last_message.body if last_message else None,
        "unread_count": unread_count,
    }


async def ensure_deal_participant(session: AsyncSession, deal_id: uuid.UUID, user: User) -> Deal:
    deal = await session.get(Deal, deal_id)
    if not deal or user.id not in {deal.buyer_id, deal.seller_id}:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


async def queue_counterparty_notification(
    session: AsyncSession,
    background_tasks: BackgroundTasks,
    deal: Deal,
    actor: User,
    text: str,
) -> None:
    recipient_id = deal.seller_id if actor.id == deal.buyer_id else deal.buyer_id
    recipient = await session.get(User, recipient_id)
    if recipient and recipient.bot_started:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, text)


async def support_ticket_out(session: AsyncSession, ticket: SupportTicket) -> SupportTicketOut:
    messages = list(
        (
            await session.scalars(
                select(SupportMessage)
                .where(SupportMessage.ticket_id == ticket.id)
                .order_by(SupportMessage.created_at)
            )
        ).all()
    )
    events = list((await session.scalars(
        select(SupportCaseEvent)
        .where(SupportCaseEvent.ticket_id == ticket.id)
        .order_by(SupportCaseEvent.created_at)
    )).all())
    listing = await session.get(Listing, ticket.listing_id) if ticket.listing_id else None
    buyer = await session.get(User, ticket.buyer_id) if ticket.buyer_id else None
    seller = await session.get(User, ticket.seller_id) if ticket.seller_id else None
    author = await session.get(User, ticket.author_id)
    conversation_messages: list[ConversationMessage] = []
    if ticket.deal_id:
        deal = await session.get(Deal, ticket.deal_id)
        conversation_id = deal.conversation_id if deal else None
        if not conversation_id:
            conversation_id = await session.scalar(select(Conversation.id).where(Conversation.deal_id == ticket.deal_id))
        if conversation_id:
            conversation_messages = list((await session.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation_id)
                .order_by(ConversationMessage.created_at)
            )).all())
    return SupportTicketOut.model_validate(ticket).model_copy(
        update={
            "messages": [SupportMessageOut.model_validate(message) for message in messages],
            "conversation_messages": [ConversationMessageOut.model_validate(message) for message in conversation_messages],
            "events": [SupportCaseEventOut.model_validate(event) for event in events],
            "listing_title": f"{listing.brand} {listing.model}".strip() if listing else None,
            "buyer": UserOut.model_validate(buyer) if buyer else None,
            "seller": UserOut.model_validate(seller) if seller else None,
            "author": UserOut.model_validate(author) if author else None,
        }
    )


async def training_purchase_out(session: AsyncSession, purchase: TrainingPurchase) -> TrainingPurchaseOut:
    materials: list[TrainingMaterial] = []
    if purchase.product_type == "automatic":
        materials = list((await session.scalars(
            select(TrainingMaterial).where(
                TrainingMaterial.product_id == purchase.product_id,
                TrainingMaterial.is_active.is_(True),
            ).order_by(TrainingMaterial.position, TrainingMaterial.created_at)
        )).all())
    return TrainingPurchaseOut.model_validate(purchase).model_copy(
        update={"materials": [TrainingMaterialPublicOut.model_validate(item) for item in materials]}
    )


async def training_purchase_admin_out(
    session: AsyncSession,
    purchase: TrainingPurchase,
    buyer: User | None = None,
) -> TrainingPurchaseAdminOut:
    buyer = buyer or await session.get(User, purchase.buyer_id)
    if not buyer:
        raise HTTPException(status_code=404, detail="Покупатель не найден")
    public = await training_purchase_out(session, purchase)
    return TrainingPurchaseAdminOut.model_validate(purchase).model_copy(update={
        "buyer": TrainingBuyerOut.model_validate(buyer),
        "materials": public.materials,
    })


async def deliver_training_materials(purchase_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        purchase = await session.get(TrainingPurchase, purchase_id)
        if not purchase or purchase.delivery_status != "sending":
            return
        buyer = await session.get(User, purchase.buyer_id)
        materials = list((await session.scalars(
            select(TrainingMaterial).where(
                TrainingMaterial.product_id == purchase.product_id,
                TrainingMaterial.is_active.is_(True),
            ).order_by(TrainingMaterial.position, TrainingMaterial.created_at)
        )).all())
        telegram_id = buyer.telegram_id if buyer and buyer.bot_started else None
    success = bool(telegram_id and materials)
    if success:
        for material in materials:
            sent = False
            for _attempt in range(2):
                sent = await send_bot_material(telegram_id, material.material_type, material.delivery_reference, material.title)
                if sent:
                    break
            if not sent:
                success = False
    async with SessionLocal() as session:
        await finish_training_delivery(session, purchase_id, success)


async def notify_personal_training_admin(purchase_id: uuid.UUID) -> None:
    """Deliver and persist the result of the personal-order Telegram notification."""
    async with SessionLocal() as session:
        purchase = await session.scalar(
            select(TrainingPurchase).where(TrainingPurchase.id == purchase_id).with_for_update()
        )
        if not purchase or purchase.product_type != "personal" or purchase.admin_notification_status == "sent":
            return
        if purchase.admin_notification_status == "sending":
            return
        purchase.admin_notification_status = "sending"
        purchase.admin_notification_attempts += 1
        purchase.admin_notification_error = None
        purchase.admin_notification_last_attempt_at = datetime.now(UTC)
        seller = await session.get(User, purchase.seller_id)
        intent = await session.scalar(
            select(StarPaymentIntent).where(StarPaymentIntent.training_purchase_id == purchase.id)
        )
        await session.commit()

    error: str | None = None
    if not seller or not seller.bot_started:
        error = "Администратор не запускал бота командой /start или заблокировал его"
    else:
        try:
            await send_personal_training_order_notification(
                seller.telegram_id,
                purchase_id=str(purchase.id),
                title=purchase.title_snapshot,
                buyer_name=purchase.buyer_display_name,
                buyer_username=purchase.buyer_username,
                buyer_telegram_id=purchase.buyer_telegram_id,
                price_xtr=int(intent.xtr_amount) if intent else int(purchase.price_af_coins),
            )
        except HTTPException as exc:
            logger.warning(
                "personal_training_admin_notification_failed purchase_id=%s status=%s detail=%s",
                purchase_id,
                exc.status_code,
                str(exc.detail)[:300],
            )
            error = str(exc.detail)
        except Exception as exc:
            logger.exception("personal_training_admin_notification_failed purchase_id=%s", purchase_id)
            error = f"{type(exc).__name__}: ошибка отправки Telegram notification"

    async with SessionLocal() as session:
        purchase = await session.scalar(
            select(TrainingPurchase).where(TrainingPurchase.id == purchase_id).with_for_update()
        )
        if not purchase:
            return
        purchase.admin_notification_status = "failed" if error else "sent"
        purchase.admin_notification_error = error
        purchase.admin_notified_at = None if error else datetime.now(UTC)
        await session.commit()


async def recover_training_background_jobs() -> None:
    """Resume persisted training work that was interrupted by a process restart."""
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(minutes=2)
    async with SessionLocal() as session:
        async with session.begin():
            personal = list((await session.scalars(
                select(TrainingPurchase)
                .where(
                    TrainingPurchase.product_type == "personal",
                    or_(
                        TrainingPurchase.admin_notification_status == "pending",
                        and_(
                            TrainingPurchase.admin_notification_status == "sending",
                            or_(
                                TrainingPurchase.admin_notification_last_attempt_at.is_(None),
                                TrainingPurchase.admin_notification_last_attempt_at < stale_cutoff,
                            ),
                        ),
                    ),
                )
                .with_for_update(skip_locked=True)
            )).all())
            for purchase in personal:
                if purchase.admin_notification_status == "sending":
                    purchase.admin_notification_status = "pending"
                    purchase.admin_notification_error = "Отправка была прервана перезапуском сервиса"
            personal_ids = [purchase.id for purchase in personal]

            automatic = list((await session.scalars(
                select(TrainingPurchase)
                .where(
                    TrainingPurchase.product_type == "automatic",
                    or_(
                        TrainingPurchase.delivery_status == "pending",
                        and_(
                            TrainingPurchase.delivery_status == "sending",
                            or_(
                                TrainingPurchase.delivery_lock_until.is_(None),
                                TrainingPurchase.delivery_lock_until < now,
                            ),
                        ),
                    ),
                )
                .with_for_update(skip_locked=True)
            )).all())
            for purchase in automatic:
                if purchase.delivery_status == "sending":
                    purchase.delivery_status = "failed"
                    purchase.delivery_lock_until = None
            automatic_jobs = [(purchase.id, purchase.buyer_id) for purchase in automatic]

    for purchase_id in personal_ids:
        await notify_personal_training_admin(purchase_id)
    for purchase_id, buyer_id in automatic_jobs:
        try:
            async with SessionLocal() as session:
                await begin_training_delivery(session, buyer_id, purchase_id, cooldown_seconds=0)
            await deliver_training_materials(purchase_id)
        except HTTPException as exc:
            logger.warning(
                "training_delivery_recovery_skipped purchase_id=%s status=%s detail=%s",
                purchase_id,
                exc.status_code,
                str(exc.detail)[:300],
            )


def normalize_image_content(content: bytes) -> tuple[bytes, str, str]:
    """Validate a real image and normalize mobile formats to a browser-safe JPEG."""

    try:
        with Image.open(BytesIO(content)) as source:
            source_format = (source.format or "").upper()
            if source_format not in {"JPEG", "PNG", "WEBP", "HEIF", "HEIC"}:
                raise HTTPException(status_code=415, detail="Разрешены фотографии JPG, PNG, WEBP, HEIC и HEIF")
            source.load()
            image = ImageOps.exif_transpose(source)
            image.thumbnail((2560, 2560), Image.Resampling.LANCZOS)
            if "A" in image.getbands():
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True, progressive=True)
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=415, detail="Файл не удалось распознать как фотографию") from exc
    normalized = output.getvalue()
    if not normalized:
        raise HTTPException(status_code=415, detail="Не удалось подготовить фотографию")
    return normalized, "image/jpeg", ".jpg"


@router.get("/health")
async def health():
    return {"status": "ok", "currency": "AF Coins", "stars_invoice_enabled": bool(get_settings().bot_token)}


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
    return MeOut(user=user, wallet=wallet)


@router.post("/uploads", status_code=201)
async def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    max_bytes = get_settings().upload_max_bytes
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Фотография превышает допустимый размер {max_bytes // (1024 * 1024)} МБ")
    normalized, content_type, _extension = normalize_image_content(content)
    image = UploadedImage(
        owner_id=user.id,
        content_type=content_type,
        data=normalized,
        size_bytes=len(normalized),
        original_filename=(Path(file.filename or "photo").name[:255] or None),
    )
    session.add(image)
    await session.commit()
    return {"url": f"/api/media/{image.id}"}


@router.get("/media/{image_id}", response_class=Response)
async def uploaded_image(image_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    image = await session.get(UploadedImage, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Фотография не найдена")
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.post("/admin/advertisement/upload", status_code=201)
async def upload_advertisement_image(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
):
    max_bytes = 2 * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="Рекламное изображение не должно превышать 2 МБ")
    normalized, _content_type, extension = normalize_image_content(content)
    filename = f"advertisement-{admin.id}-{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / filename).write_bytes(normalized)
    return {"url": f"/uploads/{filename}"}


@router.get("/advertisement", response_model=AdvertisementOut | None)
async def active_advertisement(session: AsyncSession = Depends(get_session)):
    return await session.scalar(
        select(Advertisement)
        .where(Advertisement.is_active.is_(True))
        .order_by(Advertisement.updated_at.desc())
        .limit(1)
    )


@router.get("/admin/advertisement", response_model=AdvertisementOut | None)
async def get_advertisement(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    return await session.scalar(select(Advertisement).order_by(Advertisement.updated_at.desc()).limit(1))


@router.put("/admin/advertisement", response_model=AdvertisementOut)
async def upsert_advertisement(
    payload: AdvertisementUpsert,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        advertisement = await session.scalar(
            select(Advertisement).order_by(Advertisement.updated_at.desc()).with_for_update().limit(1)
        )
        if advertisement:
            advertisement.image_url = payload.image_url
            advertisement.link_url = payload.link_url
            advertisement.is_active = payload.is_active
            advertisement.admin_id = admin.id
        else:
            advertisement = Advertisement(
                image_url=payload.image_url,
                link_url=payload.link_url,
                is_active=payload.is_active,
                admin_id=admin.id,
            )
            session.add(advertisement)
            await session.flush()
        session.add(
            AdminAction(
                admin_id=admin.id,
                action="advertisement_upsert",
                target_type="advertisement",
                target_id=advertisement.id,
            )
        )
    await session.refresh(advertisement)
    return advertisement


@router.delete("/admin/advertisement", status_code=204)
async def delete_advertisement(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        advertisement = await session.scalar(
            select(Advertisement).order_by(Advertisement.updated_at.desc()).with_for_update().limit(1)
        )
        if not advertisement:
            raise HTTPException(status_code=404, detail="Реклама не найдена")
        advertisement_id = advertisement.id
        await session.delete(advertisement)
        session.add(
            AdminAction(
                admin_id=admin.id,
                action="advertisement_delete",
                target_type="advertisement",
                target_id=advertisement_id,
            )
        )


@router.get("/listings", response_model=list[ListingOut])
async def list_listings(
    listing_type: str = Query(alias="type", pattern="^(regular|unique)$"),
    brand: str | None = None,
    min_price: Decimal | None = Query(default=None, ge=0),
    max_price: Decimal | None = Query(default=None, ge=0),
    min_power: int | None = Query(default=None, gt=0),
    min_speed: int | None = Query(default=None, gt=0),
    session: AsyncSession = Depends(get_session),
):
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(status_code=422, detail="Цена от не может быть больше цены до")
    await expire_promotions(session)
    query = select(Listing).where(Listing.listing_type == listing_type, Listing.status.in_(["active", "reserved"]))
    if brand:
        query = query.where(Listing.brand == brand)
    if min_price is not None:
        query = query.where(Listing.price_af_coins >= min_price)
    if max_price is not None:
        query = query.where(Listing.price_af_coins <= max_price)
    if min_power:
        query = query.where(Listing.power_hp >= min_power)
    if min_speed:
        query = query.where(Listing.max_speed_kph >= min_speed)
    listings = list((await session.scalars(query.order_by(Listing.pinned.desc(), Listing.created_at.desc()))).all())
    return [await listing_out(session, item) for item in listings]


@router.post("/listings", response_model=ListingOut, status_code=201)
async def add_regular_listing(
    payload: ListingCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    listing = await create_listing(session, user, payload, listing_type="regular")
    return await listing_out(session, listing)


@router.get("/listings/{listing_id}", response_model=ListingOut)
async def get_listing_details(
    listing_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    listing = await session.get(Listing, listing_id)
    if not listing or listing.status == "deleted":
        raise HTTPException(status_code=404, detail="Объявление не найдено")
    if listing.seller_id != user.id:
        listing.views_count += 1
        await session.commit()
        await session.refresh(listing)
    return await listing_out(session, listing, user.id)


@router.post("/listings/{listing_id}/purchase", response_model=DealOut)
async def buy_listing_now(
    listing_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    deal, seller_telegram_id, created = await purchase_listing(session, user, listing_id)
    if created and seller_telegram_id:
        background_tasks.add_task(
            send_bot_notification,
            seller_telegram_id,
            "Ваш товар хотят купить. Покупатель оплатил, деньги находятся под защитой. Откройте AUTOFLOW MARKET.",
        )
    return deal


@router.patch("/listings/{listing_id}", response_model=ListingOut)
async def edit_own_listing(listing_id: uuid.UUID, payload: ListingUpdate, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    listing = await update_listing(session, user, listing_id, payload)
    return await listing_out(session, listing, user.id)


@router.delete("/listings/{listing_id}", status_code=204)
async def remove_own_listing(listing_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await delete_listing(session, user, listing_id)


@router.post("/listings/{listing_id}/promote", response_model=ListingOut)
async def promote_own_listing(listing_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    listing = await promote_listing(session, user, listing_id)
    return await listing_out(session, listing, user.id)


@router.post("/admin/listings/unique", response_model=ListingOut, status_code=201)
async def add_unique_listing(
    payload: UniqueListingCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    listing = await create_listing(session, admin, payload, listing_type="unique", pinned=payload.pinned)
    return await listing_out(session, listing)


@router.patch("/admin/listings/{listing_id}", response_model=ListingOut)
async def edit_unique_listing(
    listing_id: uuid.UUID,
    payload: ListingUpdate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    listing = await update_listing(session, admin, listing_id, payload)
    return await listing_out(session, listing)


@router.delete("/admin/listings/{listing_id}", status_code=204)
async def remove_unique_listing(
    listing_id: uuid.UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await delete_listing(session, admin, listing_id)


@router.get("/accounts", response_model=list[AccountListingOut])
async def list_account_listings(session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(AccountListing).where(AccountListing.status == "active").order_by(AccountListing.created_at.desc()))).all())


@router.post("/admin/accounts", response_model=AccountListingOut, status_code=201)
async def add_account_listing(payload: AccountListingCreate, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return await create_account_listing(session, admin, payload)


@router.patch("/admin/accounts/{account_id}", response_model=AccountListingOut)
async def edit_account_listing(account_id: uuid.UUID, payload: AccountListingUpdate, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return await update_account_listing(session, admin, account_id, payload)


@router.delete("/admin/accounts/{account_id}", status_code=204)
async def remove_account_listing(account_id: uuid.UUID, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    await delete_account_listing(session, admin, account_id)


@router.get("/training", response_model=list[TrainingProductOut])
async def list_training_products(session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(
        select(TrainingProduct).where(
            TrainingProduct.published.is_(True),
            TrainingProduct.deleted_at.is_(None),
        ).order_by(TrainingProduct.pinned.desc(), TrainingProduct.created_at.desc())
    )).all())


@router.get("/training/mine", response_model=list[TrainingPurchaseOut])
async def my_training_purchases(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    purchases = list((await session.scalars(
        select(TrainingPurchase)
        .where(TrainingPurchase.buyer_id == user.id)
        .order_by(TrainingPurchase.created_at.desc())
    )).all())
    return [await training_purchase_out(session, purchase) for purchase in purchases]


@router.get("/training/{product_id}", response_model=TrainingProductOut)
async def get_training_product(product_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    product = await session.scalar(select(TrainingProduct).where(
        TrainingProduct.id == product_id,
        TrainingProduct.published.is_(True),
        TrainingProduct.deleted_at.is_(None),
    ))
    if not product:
        raise HTTPException(status_code=404, detail="Обучение не найдено")
    return product


@router.post("/training/{product_id}/purchase-intent", response_model=StarPaymentIntentOut, status_code=201)
async def create_training_purchase_intent(
    product_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    intent = await create_training_payment_intent(session, user, product_id, create_training_invoice_link)
    return StarPaymentIntentOut(
        id=intent.id,
        invoice_url=intent.invoice_link,
        amount=intent.xtr_amount,
        status=intent.status,
        purpose=intent.purpose,
        training_product_id=intent.training_product_id,
        training_purchase_id=intent.training_purchase_id,
        checkout_status=intent.checkout_status,
    )


@router.post("/training/{product_id}/purchase", status_code=409)
async def legacy_training_purchase(product_id: uuid.UUID, user: User = Depends(get_current_user)):
    del product_id, user
    raise HTTPException(status_code=409, detail="Создайте защищённый Telegram Stars invoice через purchase-intent")


@router.post("/training/purchases/{purchase_id}/redeliver", response_model=TrainingPurchaseOut)
async def redeliver_training_purchase(
    purchase_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    purchase = await begin_training_delivery(
        session,
        user.id,
        purchase_id,
        cooldown_seconds=settings.training_delivery_cooldown_seconds,
    )
    background_tasks.add_task(deliver_training_materials, purchase.id)
    return await training_purchase_out(session, purchase)


@router.get("/admin/training", response_model=list[TrainingProductOut])
async def list_admin_training_products(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(
        select(TrainingProduct).where(
            TrainingProduct.admin_id == admin.id,
            TrainingProduct.deleted_at.is_(None),
        ).order_by(TrainingProduct.pinned.desc(), TrainingProduct.created_at.desc())
    )).all())


@router.get("/admin/training/management", response_model=list[TrainingAdminProductOut])
async def manage_training_products(
    filter: str = Query(default="all", pattern="^(all|published|hidden|pinned|personal|automatic)$"),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    aggregate = (
        select(
            TrainingPurchase.product_id.label("product_id"),
            func.count(TrainingPurchase.id).label("purchase_count"),
            func.coalesce(func.sum(TrainingPurchase.price_af_coins), 0).label("revenue"),
        )
        .group_by(TrainingPurchase.product_id)
        .subquery()
    )
    statement = (
        select(TrainingProduct, aggregate.c.purchase_count, aggregate.c.revenue)
        .outerjoin(aggregate, aggregate.c.product_id == TrainingProduct.id)
        .where(TrainingProduct.admin_id == admin.id)
        .order_by(TrainingProduct.pinned.desc(), TrainingProduct.created_at.desc())
    )
    if filter == "published":
        statement = statement.where(TrainingProduct.published.is_(True), TrainingProduct.deleted_at.is_(None))
    elif filter == "hidden":
        statement = statement.where(or_(TrainingProduct.published.is_(False), TrainingProduct.deleted_at.is_not(None)))
    elif filter == "pinned":
        statement = statement.where(TrainingProduct.pinned.is_(True), TrainingProduct.deleted_at.is_(None))
    elif filter in {"personal", "automatic"}:
        statement = statement.where(TrainingProduct.product_type == filter)
    rows = (await session.execute(statement)).all()
    return [
        TrainingAdminProductOut.model_validate(product).model_copy(update={
            "purchase_count": int(count or 0),
            "revenue_af_coins": Decimal(revenue or 0),
            "archived": product.deleted_at is not None,
        })
        for product, count, revenue in rows
    ]


@router.get("/admin/training/stats", response_model=TrainingAdminStatsOut)
async def training_stats(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    total_sales, total_revenue, personal_sales, automatic_sales = (await session.execute(
        select(
            func.count(TrainingPurchase.id),
            func.coalesce(func.sum(TrainingPurchase.price_af_coins), 0),
            func.count(TrainingPurchase.id).filter(TrainingPurchase.product_type == "personal"),
            func.count(TrainingPurchase.id).filter(TrainingPurchase.product_type == "automatic"),
        ).where(TrainingPurchase.seller_id == admin.id)
    )).one()
    return TrainingAdminStatsOut(
        total_sales=int(total_sales or 0),
        total_revenue_af_coins=Decimal(total_revenue or 0),
        personal_sales=int(personal_sales or 0),
        automatic_sales=int(automatic_sales or 0),
    )


@router.post("/admin/training", response_model=TrainingProductOut, status_code=201)
async def add_training_product(payload: TrainingProductCreate, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return await create_training_product(session, admin, payload)


@router.patch("/admin/training/{product_id}", response_model=TrainingProductOut)
async def edit_training_product(product_id: uuid.UUID, payload: TrainingProductUpdate, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return await update_training_product(session, admin, product_id, payload)


@router.post("/admin/training/{product_id}/state/{action}", response_model=TrainingProductOut)
async def change_training_product_state(
    product_id: uuid.UUID,
    action: str,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    return await set_training_product_state(session, admin, product_id, action)


@router.get("/admin/training/{product_id}/materials", response_model=list[TrainingMaterialAdminOut])
async def list_training_materials(
    product_id: uuid.UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    product = await session.get(TrainingProduct, product_id)
    if not product or product.admin_id != admin.id:
        raise HTTPException(status_code=404, detail="Обучение не найдено")
    return list((await session.scalars(
        select(TrainingMaterial).where(TrainingMaterial.product_id == product_id, TrainingMaterial.is_active.is_(True))
        .order_by(TrainingMaterial.position, TrainingMaterial.created_at)
    )).all())


@router.post("/admin/training/{product_id}/materials", response_model=TrainingMaterialAdminOut, status_code=201)
async def add_training_material(
    product_id: uuid.UUID,
    payload: TrainingMaterialCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    return await create_training_material(session, admin, product_id, payload)


@router.post("/admin/training/materials/upload", status_code=201)
async def upload_training_material(
    material_type: str = Query(pattern="^(photo|video|document)$"),
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
):
    content = await file.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Материал не должен превышать 20 МБ")
    if not content:
        raise HTTPException(status_code=400, detail="Файл пуст")
    return await upload_bot_material(
        admin.telegram_id,
        material_type,
        file.filename or "material",
        content,
        file.content_type or "application/octet-stream",
    )


@router.patch("/admin/training/materials/{material_id}", response_model=TrainingMaterialAdminOut)
async def edit_training_material(
    material_id: uuid.UUID,
    payload: TrainingMaterialUpdate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    return await update_training_material(session, admin, material_id, payload)


@router.delete("/admin/training/materials/{material_id}", status_code=204)
async def remove_training_material(
    material_id: uuid.UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await delete_training_material(session, admin, material_id)


@router.get("/admin/training/purchases", response_model=list[TrainingPurchaseAdminOut])
async def all_training_orders(
    product_type: str | None = Query(default=None, pattern="^(personal|automatic)$"),
    purchase_status: str | None = Query(default=None, pattern="^(awaiting_start|in_progress|completed)$"),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    statement = select(TrainingPurchase).where(TrainingPurchase.seller_id == admin.id)
    if product_type:
        statement = statement.where(TrainingPurchase.product_type == product_type)
    if purchase_status:
        statement = statement.where(TrainingPurchase.status == purchase_status)
    purchases = list((await session.scalars(statement.order_by(TrainingPurchase.created_at.desc()))).all())
    buyer_ids = {purchase.buyer_id for purchase in purchases}
    buyers = list((await session.scalars(select(User).where(User.id.in_(buyer_ids)))).all()) if buyer_ids else []
    by_id = {buyer.id: buyer for buyer in buyers}
    return [await training_purchase_admin_out(session, purchase, by_id.get(purchase.buyer_id)) for purchase in purchases]


@router.get("/admin/training/{product_id}/purchases", response_model=list[TrainingPurchaseAdminOut])
async def training_product_buyers(
    product_id: uuid.UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    product = await session.get(TrainingProduct, product_id)
    if not product or product.admin_id != admin.id:
        raise HTTPException(status_code=404, detail="Обучение не найдено")
    purchases = list((await session.scalars(
        select(TrainingPurchase).where(TrainingPurchase.product_id == product_id).order_by(TrainingPurchase.created_at.desc())
    )).all())
    buyer_ids = {item.buyer_id for item in purchases}
    users = list((await session.scalars(select(User).where(User.id.in_(buyer_ids)))).all()) if buyer_ids else []
    users_by_id = {item.id: item for item in users}
    results = []
    for purchase in purchases:
        buyer = users_by_id.get(purchase.buyer_id)
        if not buyer:
            continue
        results.append(await training_purchase_admin_out(session, purchase, buyer))
    return results


@router.patch("/admin/training/purchases/{purchase_id}/status", response_model=TrainingPurchaseAdminOut)
async def change_training_purchase_status(
    purchase_id: uuid.UUID,
    payload: TrainingPurchaseStatusUpdate,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    purchase = await update_training_purchase_status(session, admin, purchase_id, payload.status)
    buyer = await session.get(User, purchase.buyer_id)
    if buyer and buyer.bot_started:
        text = "🎓 Ваш заказ принят в работу." if payload.status == "in_progress" else "✅ Персональное обучение завершено."
        background_tasks.add_task(send_bot_notification, buyer.telegram_id, text)
    if not buyer:
        raise HTTPException(status_code=404, detail="Покупатель не найден")
    return await training_purchase_admin_out(session, purchase, buyer)


@router.post("/admin/training/purchases/{purchase_id}/notify", response_model=TrainingPurchaseAdminOut)
async def retry_personal_training_notification(
    purchase_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    purchase = await session.scalar(
        select(TrainingPurchase).where(TrainingPurchase.id == purchase_id).with_for_update()
    )
    if not purchase:
        raise HTTPException(status_code=404, detail="Заказ обучения не найден")
    if purchase.seller_id != admin.id or purchase.product_type != "personal":
        raise HTTPException(status_code=403, detail="Нет доступа к заказу")
    if purchase.admin_notification_status == "sent":
        buyer = await session.get(User, purchase.buyer_id)
        return await training_purchase_admin_out(session, purchase, buyer)
    if (
        purchase.admin_notification_status == "sending"
        and purchase.admin_notification_last_attempt_at
        and purchase.admin_notification_last_attempt_at > datetime.now(UTC) - timedelta(minutes=2)
    ):
        raise HTTPException(status_code=409, detail="Уведомление уже отправляется. Повторите через две минуты")
    purchase.admin_notification_status = "pending"
    purchase.admin_notification_error = None
    await session.commit()
    background_tasks.add_task(notify_personal_training_admin, purchase.id)
    buyer = await session.get(User, purchase.buyer_id)
    return await training_purchase_admin_out(session, purchase, buyer)


@router.post("/admin/training/purchases/{purchase_id}/redeliver", response_model=TrainingPurchaseAdminOut)
async def admin_redeliver_training_purchase(
    purchase_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    purchase = await session.get(TrainingPurchase, purchase_id)
    if not purchase:
        raise HTTPException(status_code=404, detail="Покупка не найдена")
    if purchase.seller_id != admin.id or purchase.product_type != "automatic":
        raise HTTPException(status_code=403, detail="Нет доступа к автовыдаче")
    purchase = await begin_training_delivery(
        session,
        purchase.buyer_id,
        purchase.id,
        cooldown_seconds=settings.training_delivery_cooldown_seconds,
    )
    background_tasks.add_task(deliver_training_materials, purchase.id)
    buyer = await session.get(User, purchase.buyer_id)
    return await training_purchase_admin_out(session, purchase, buyer)


@router.delete("/admin/training/{product_id}", status_code=204)
async def remove_training_product(product_id: uuid.UUID, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    await delete_training_product(session, admin, product_id)


@router.get("/cart", response_model=list[ListingOut])
async def get_cart(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    listing_ids = list((await session.scalars(select(CartItem.listing_id).where(CartItem.user_id == user.id).order_by(CartItem.created_at))).all())
    if not listing_ids:
        return []
    listings = list((await session.scalars(select(Listing).where(Listing.id.in_(listing_ids)))).all())
    by_id = {item.id: item for item in listings}
    return [await listing_out(session, by_id[item_id], user.id) for item_id in listing_ids if item_id in by_id]


@router.post("/cart/items/{listing_id}", status_code=201)
async def add_to_cart(listing_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    listing = await session.get(Listing, listing_id)
    if not listing or listing.status != "active":
        raise HTTPException(status_code=409, detail="Listing is not available")
    if listing.seller_id == user.id:
        raise HTTPException(status_code=400, detail="You cannot add your own listing to cart")
    if not await session.scalar(select(CartItem.id).where(CartItem.user_id == user.id, CartItem.listing_id == listing_id)):
        session.add(CartItem(user_id=user.id, listing_id=listing_id))
        await session.commit()
    return {"ok": True}


@router.delete("/cart/items/{listing_id}", status_code=204)
async def delete_from_cart(listing_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await session.execute(delete(CartItem).where(CartItem.user_id == user.id, CartItem.listing_id == listing_id))
    await session.commit()


@router.post("/cart/checkout", response_model=list[DealOut])
async def checkout(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    deals, seller_ids = await checkout_cart(session, user)
    for telegram_id in seller_ids:
        background_tasks.add_task(send_bot_notification, telegram_id, "Ваш товар хотят купить. Откройте AUTOFLOW MARKET, чтобы ответить покупателю")
    return deals


@router.get("/favorites", response_model=list[ListingOut])
async def get_favorites(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    listing_ids = list((await session.scalars(select(Favorite.listing_id).where(Favorite.user_id == user.id).order_by(Favorite.created_at.desc()))).all())
    if not listing_ids:
        return []
    listings = list((await session.scalars(select(Listing).where(Listing.id.in_(listing_ids)))).all())
    by_id = {item.id: item for item in listings}
    return [await listing_out(session, by_id[item_id]) for item_id in listing_ids if item_id in by_id]


@router.post("/favorites/{listing_id}", status_code=201)
async def add_favorite(listing_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    if not await session.get(Listing, listing_id):
        raise HTTPException(status_code=404, detail="Listing not found")
    if not await session.scalar(select(Favorite.id).where(Favorite.user_id == user.id, Favorite.listing_id == listing_id)):
        session.add(Favorite(user_id=user.id, listing_id=listing_id))
        await session.commit()
    return {"ok": True}


@router.delete("/favorites/{listing_id}", status_code=204)
async def remove_favorite(listing_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await session.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.listing_id == listing_id))
    await session.commit()


@router.post("/conversations/listing/{listing_id}", status_code=201)
async def start_conversation(
    listing_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conversation, seller, listing = await get_or_create_conversation(session, user, listing_id, create=False)
    if conversation:
        details = await conversation_details(session, conversation, user)
        details["listing"] = await listing_out(session, listing, user.id)
        return details
    return {
        "id": None,
        "draft": True,
        "listing": await listing_out(session, listing, user.id),
        "deal": None,
        "buyer_id": str(user.id),
        "seller_id": str(seller.id),
        "counterparty": {
            "id": str(seller.id),
            "name": " ".join(filter(None, [seller.first_name, seller.last_name])),
            "username": seller.username,
            "photo_url": seller.photo_url,
            "mini_app_last_active_at": seller.mini_app_last_active_at,
        },
        "offers": [],
        "last_message": None,
        "unread_count": 0,
    }


@router.get("/conversations")
async def list_conversations(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    values = list(
        (
            await session.scalars(
                select(Conversation)
                .where(
                    or_(
                        and_(Conversation.buyer_id == user.id, Conversation.buyer_hidden_at.is_(None)),
                        and_(Conversation.seller_id == user.id, Conversation.seller_hidden_at.is_(None)),
                    ),
                    or_(Conversation.last_message_at.is_not(None), Conversation.deal_id.is_not(None)),
                )
                .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc())
            )
        ).all()
    )
    return [await conversation_details(session, item, user) for item in values]

@router.get("/conversations/unread-summary")
async def conversation_unread_summary(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conversations = list(
        (
            await session.scalars(
                select(Conversation).where(
                    or_(
                        Conversation.buyer_id == user.id,
                        Conversation.seller_id == user.id,
                    )
                )
            )
        ).all()
    )

    conversation_ids = [conversation.id for conversation in conversations]

    if not conversation_ids:
        return {
            "total_unread": 0,
            "conversations": [],
        }

    unread_rows = (
        await session.execute(
            select(
                ConversationMessage.conversation_id,
                func.count(ConversationMessage.id),
            )
            .where(
                ConversationMessage.conversation_id.in_(conversation_ids),
                ConversationMessage.sender_id != user.id,
                ConversationMessage.is_read.is_(False),
            )
            .group_by(ConversationMessage.conversation_id)
        )
    ).all()

    unread_by_conversation = {
        str(conversation_id): unread_count
        for conversation_id, unread_count in unread_rows
    }

    return {
        "total_unread": sum(unread_by_conversation.values()),
        "conversations": [
            {
                "conversation_id": conversation_id,
                "unread_count": unread_count,
            }
            for conversation_id, unread_count in unread_by_conversation.items()
        ],
    }

@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    conversation = await session.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await conversation_details(session, conversation, user)


@router.get("/conversations/{conversation_id}/messages", response_model=list[ConversationMessageOut])
async def get_conversation_messages(conversation_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    conversation = await session.get(Conversation, conversation_id)
    if not conversation or user.id not in {conversation.buyer_id, conversation.seller_id}:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return list((await session.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id).order_by(ConversationMessage.created_at))).all())

@router.post("/conversations/{conversation_id}/read", status_code=204)
async def mark_conversation_as_read(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conversation = await session.get(Conversation, conversation_id)

    if not conversation or user.id not in {
        conversation.buyer_id,
        conversation.seller_id,
    }:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    await session.execute(
        update(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.sender_id != user.id,
            ConversationMessage.is_read.is_(False),
        )
        .values(
            is_read=True,
            read_at=datetime.now(UTC),
        )
    )

    await session.commit()


@router.post("/conversations/{conversation_id}/messages", response_model=ConversationMessageOut, status_code=201)
async def add_conversation_message(
    conversation_id: uuid.UUID,
    payload: ConversationMessageCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    message, recipient, created = await send_conversation_message(session, user, conversation_id, payload.body, payload.client_message_id)
    if created and recipient and recipient.bot_started:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, "Новое сообщение в AUTOFLOW MARKET. Откройте приложение, чтобы ответить")
    return message


@router.post("/conversations/listing/{listing_id}/messages", response_model=ConversationMessageOut, status_code=201)
async def add_first_conversation_message(
    listing_id: uuid.UUID,
    payload: ConversationMessageCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conversation, _, _ = await get_or_create_conversation(session, user, listing_id, create=True)
    message, recipient, created = await send_conversation_message(
        session, user, conversation.id, payload.body, payload.client_message_id
    )
    if created and recipient and recipient.bot_started:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, "Новое сообщение в AUTOFLOW MARKET. Откройте приложение, чтобы ответить")
    return message


@router.post("/conversations/{conversation_id}/hide", status_code=204)
async def hide_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conversation = await session.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
    if not conversation or user.id not in {conversation.buyer_id, conversation.seller_id}:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user.id == conversation.buyer_id:
        conversation.buyer_hidden_at = datetime.now(UTC)
    else:
        conversation.seller_hidden_at = datetime.now(UTC)
    await session.commit()


@router.post("/conversations/{conversation_id}/offers", response_model=PriceOfferOut, status_code=201)
async def add_price_offer(
    conversation_id: uuid.UUID,
    payload: PriceOfferCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    offer, recipient = await create_price_offer(session, user, conversation_id, payload.amount_af_coins)
    if recipient and recipient.bot_started:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, f"Новое предложение цены: {offer.amount_af_coins} AF Coins")
    return offer


@router.post("/conversations/{conversation_id}/offers/counter", response_model=PriceOfferOut, status_code=201)
async def counter_price_offer(
    conversation_id: uuid.UUID,
    payload: CounterOfferCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    offer, recipient = await create_price_offer(session, user, conversation_id, payload.amount_af_coins, payload.parent_offer_id)
    if recipient and recipient.bot_started:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, f"Встречное предложение: {offer.amount_af_coins} AF Coins")
    return offer


@router.post("/offers/{offer_id}/{action}", response_model=PriceOfferOut)
async def answer_price_offer(
    offer_id: uuid.UUID,
    action: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if action not in {"accept", "reject"}:
        raise HTTPException(status_code=404, detail="Unknown offer action")
    offer, recipient = await respond_price_offer(session, user, offer_id, action == "accept")
    if recipient and recipient.bot_started:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, "Ваше предложение цены принято" if action == "accept" else "Ваше предложение цены отклонено")
    return offer


@router.get("/deals", response_model=list[DealOut])
async def list_deals(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(Deal).where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id)).order_by(Deal.updated_at.desc()))).all())


@router.get("/deals/{deal_id}")
async def get_deal(deal_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    deal = await ensure_deal_participant(session, deal_id, user)
    listing = await session.get(Listing, deal.listing_id)
    other_id = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
    other = await session.get(User, other_id)
    conversation_id = deal.conversation_id or await session.scalar(select(Conversation.id).where(Conversation.deal_id == deal.id))
    return {
        "deal": DealOut.model_validate(deal),
        "listing": await listing_out(session, listing),
        "counterparty": {
            "id": str(other.id),
            "name": " ".join(filter(None, [other.first_name, other.last_name])),
            "username": other.username,
            "photo_url": other.photo_url,
            "mini_app_last_active_at": other.mini_app_last_active_at,
        },
        "buyer_confirmation_available_at": deal.transfer_started_at,
        "conversation_id": str(conversation_id) if conversation_id else None,
    }


@router.post("/deals/{deal_id}/conversation", status_code=200)
async def open_deal_conversation(
    deal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conversation = await get_or_create_deal_conversation(session, user, deal_id)
    deal = await session.get(Deal, deal_id)
    return await conversation_details(session, conversation, user, deal_override=deal)


@router.get("/deals/{deal_id}/messages", response_model=list[MessageOut])
async def get_messages(deal_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await ensure_deal_participant(session, deal_id, user)
    return list((await session.scalars(select(DealMessage).where(DealMessage.deal_id == deal_id).order_by(DealMessage.created_at))).all())


@router.post("/deals/{deal_id}/messages", response_model=MessageOut, status_code=201)
async def send_message(
    deal_id: uuid.UUID,
    payload: MessageCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    deal = await ensure_deal_participant(session, deal_id, user)
    message = DealMessage(deal_id=deal.id, sender_id=user.id, body=payload.body.strip())
    session.add(message)
    recipient_id = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
    await create_notification(session, recipient_id, "deal_message", "Новое сообщение по сделке", payload.body[:240], {"deal_id": str(deal.id)})
    recipient = await session.get(User, recipient_id)
    await session.commit()
    await session.refresh(message)
    if recipient:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, "Новое сообщение в AUTOFLOW MARKET. Откройте приложение, чтобы ответить")
    return message


@router.post("/deals/{deal_id}/seller-contacted", response_model=DealOut)
async def seller_contacted(deal_id: uuid.UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    deal = await set_deal_status(session, user, deal_id, "seller_contacted")
    await queue_counterparty_notification(session, background_tasks, deal, user, "Продавец ответил по сделке в AUTOFLOW MARKET")
    return deal


@router.post("/deals/{deal_id}/transfer", response_model=DealOut)
async def transfer_started(deal_id: uuid.UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    deal = await set_deal_status(session, user, deal_id, "transfer_in_progress")
    await queue_counterparty_notification(session, background_tasks, deal, user, "Продавец начал передачу товара. Откройте сделку в AUTOFLOW MARKET")
    return deal


@router.post("/deals/{deal_id}/confirm", response_model=DealOut)
async def confirm_received(deal_id: uuid.UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    deal = await complete_deal(session, user, deal_id)
    await queue_counterparty_notification(session, background_tasks, deal, user, "Покупатель подтвердил получение. Сделка завершена, 70% начислено в AF Coins")
    return deal


@router.post("/deals/{deal_id}/dispute", response_model=DealOut)
async def dispute(deal_id: uuid.UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    del deal_id, background_tasks, user, session
    raise HTTPException(status_code=410, detail="Используйте обращение в поддержку по сделке")


@router.post("/deals/{deal_id}/support", response_model=SupportTicketOut, status_code=201)
async def create_deal_support(
    deal_id: uuid.UUID,
    payload: DealSupportCaseCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ticket, listing, buyer, seller, administrators = await create_deal_support_case(
        session, user, deal_id, payload.message, payload.client_request_id
    )

    def label(person: User) -> str:
        return f"@{person.username}" if person.username else f"{person.first_name} (ID {person.telegram_id})"

    for administrator in administrators:
        if administrator.bot_started:
            background_tasks.add_task(
                send_deal_support_case_notification,
                administrator.telegram_id,
                ticket_id=str(ticket.id),
                deal_id=str(deal_id),
                listing_title=f"{listing.brand} {listing.model}".strip(),
                buyer_label=label(buyer),
                seller_label=label(seller),
                author_label=label(user),
                reason=payload.message.strip(),
            )
    return await support_ticket_out(session, ticket)


@router.post("/deals/{deal_id}/cancel", response_model=DealOut)
async def cancel(deal_id: uuid.UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    deal = await cancel_deal(session, user, deal_id)
    await queue_counterparty_notification(session, background_tasks, deal, user, "Сделка отменена. Защищённые средства возвращены покупателю")
    return deal


@router.get("/wallet", response_model=WalletOut)
async def wallet(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return await session.scalar(select(Wallet).where(Wallet.user_id == user.id))


@router.post("/wallet/star-payments/intent", response_model=StarPaymentIntentOut, status_code=201)
async def add_star_payment_intent(
    payload: StarPaymentIntentCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    intent = await create_star_payment_intent(session, user, payload.amount, create_star_invoice_link, payload.purpose)
    return StarPaymentIntentOut(
        id=intent.id,
        invoice_url=intent.invoice_link,
        amount=intent.xtr_amount,
        status=intent.status,
        purpose=intent.purpose,
        listing_id=intent.listing_id,
        missing_af_coins=intent.missing_af_coins,
        checkout_status=intent.checkout_status,
    )


@router.post("/listings/{listing_id}/purchase-topup-intent", response_model=StarPaymentIntentOut, status_code=201)
async def add_listing_purchase_topup_intent(
    listing_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    intent = await create_listing_payment_intent(session, user, listing_id, create_star_invoice_link)
    return StarPaymentIntentOut(
        id=intent.id,
        invoice_url=intent.invoice_link,
        amount=intent.xtr_amount,
        status=intent.status,
        purpose=intent.purpose,
        listing_id=intent.listing_id,
        missing_af_coins=intent.missing_af_coins,
        checkout_status=intent.checkout_status,
    )


@router.get("/wallet/star-payments/intents/{intent_id}", response_model=StarPaymentStatusOut)
async def star_payment_status(
    intent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    intent = await session.get(StarPaymentIntent, intent_id)
    if not intent or intent.user_id != user.id:
        raise HTTPException(status_code=404, detail="Счёт не найден")
    wallet_value = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
    messages = {
        "completed": "Покупка оформлена. Деньги находятся под защитой.",
        "listing_unavailable": "Объявление уже недоступно. Пополненные AF Coins сохранены на вашем балансе.",
        "failed": "Покупка не завершена. Пополненные AF Coins сохранены на вашем балансе.",
        "pending": "Оплата подтверждена. Сервер завершает покупку.",
    }
    message = messages.get(intent.checkout_status)
    if intent.purpose == "training_checkout" and intent.checkout_status == "completed":
        message = "Обучение оплачено. Заказ сохранён в вашей библиотеке."
    return StarPaymentStatusOut(
        id=intent.id,
        status=intent.status,
        amount=intent.xtr_amount,
        wallet=wallet_value,
        purpose=intent.purpose,
        listing_id=intent.listing_id,
        deal_id=intent.deal_id,
        training_product_id=intent.training_product_id,
        training_purchase_id=intent.training_purchase_id,
        checkout_status=intent.checkout_status,
        message=message,
    )


@router.post("/wallet/star-payments/intents/{intent_id}/resume-checkout", response_model=StarPaymentStatusOut)
async def resume_listing_checkout(
    intent_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    intent, deal, seller_telegram_id = await complete_listing_payment_intent(session, user, intent_id)
    if deal and seller_telegram_id:
        background_tasks.add_task(
            send_bot_notification,
            seller_telegram_id,
            "Ваш товар хотят купить. Покупатель оплатил, деньги находятся под защитой. Откройте AUTOFLOW MARKET.",
        )
    wallet_value = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
    messages = {
        "completed": "Покупка оформлена. Деньги находятся под защитой.",
        "listing_unavailable": "Объявление уже недоступно. Пополненные AF Coins сохранены на вашем балансе.",
        "failed": "Покупка не завершена. Пополненные AF Coins сохранены на вашем балансе.",
    }
    return StarPaymentStatusOut(
        id=intent.id,
        status=intent.status,
        amount=intent.xtr_amount,
        wallet=wallet_value,
        purpose=intent.purpose,
        listing_id=intent.listing_id,
        deal_id=intent.deal_id,
        checkout_status=intent.checkout_status,
        message=messages.get(intent.checkout_status),
    )


@router.get("/withdrawals", response_model=list[WithdrawalOut])
async def withdrawals(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(WithdrawalRequest).where(WithdrawalRequest.user_id == user.id).order_by(WithdrawalRequest.created_at.desc()))).all())


@router.post("/withdrawals", response_model=WithdrawalOut, status_code=201)
async def add_withdrawal(payload: WithdrawalCreate, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    withdrawal = await create_withdrawal(session, user, payload)
    admin_telegram_ids = list((await session.scalars(select(User.telegram_id).where(User.role == "admin", User.bot_started.is_(True)))).all())
    for telegram_id in admin_telegram_ids:
        background_tasks.add_task(send_bot_notification, telegram_id, f"Новая заявка на вывод: {withdrawal.amount} AF Coins от Telegram ID {user.telegram_id}")
    return withdrawal


@router.post("/withdrawals/{withdrawal_id}/cancel", response_model=WithdrawalOut)
async def cancel_own_withdrawal(withdrawal_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return await cancel_withdrawal(session, user, withdrawal_id)


@router.get("/admin/users")
async def admin_users(
    q: str | None = None,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    query = select(User).order_by(User.created_at.desc()).limit(100)
    if q:
        pattern = f"%{q.strip()}%"
        conditions = [User.first_name.ilike(pattern), User.username.ilike(pattern)]
        if q.strip().isdigit():
            conditions.append(User.telegram_id == int(q.strip()))
        query = query.where(or_(*conditions))
    users = list((await session.scalars(query)).all())
    result = []
    for item in users:
        wallet_value = await session.scalar(select(Wallet).where(Wallet.user_id == item.id))
        result.append({
            "user": UserOut.model_validate(item),
            "wallet": WalletOut.model_validate(wallet_value),
            "listings_count": await session.scalar(select(func.count(Listing.id)).where(Listing.seller_id == item.id)),
            "deals_count": await session.scalar(select(func.count(Deal.id)).where(or_(Deal.buyer_id == item.id, Deal.seller_id == item.id))),
        })
    return result


@router.get("/admin/users/{user_id}")
async def admin_user_details(user_id: uuid.UUID, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    wallet_value = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
    listings = list((await session.scalars(select(Listing).where(Listing.seller_id == user.id).order_by(Listing.created_at.desc()))).all())
    deals = list((await session.scalars(select(Deal).where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id)).order_by(Deal.created_at.desc()))).all())
    return {"user": UserOut.model_validate(user), "wallet": WalletOut.model_validate(wallet_value), "listings": [await listing_out(session, item) for item in listings], "deals": [DealOut.model_validate(item) for item in deals]}


@router.post("/admin/users/{user_id}/{action}")
async def admin_user_block_action(user_id: uuid.UUID, action: str, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    if action not in {"block", "unblock"}:
        raise HTTPException(status_code=404, detail="Unknown user action")
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Administrator cannot block themselves")
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_blocked = action == "block"
    session.add(AdminAction(admin_id=admin.id, action=f"user_{action}", target_type="user", target_id=user.id))
    await session.commit()
    return {"ok": True, "is_blocked": user.is_blocked}


@router.get("/admin/listings", response_model=list[ListingOut])
async def admin_listings(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    await expire_promotions(session)
    values = list((await session.scalars(select(Listing).where(Listing.status != "deleted").order_by(Listing.created_at.desc()))).all())
    return [await listing_out(session, item) for item in values]


@router.post("/admin/listings/{listing_id}/promote", response_model=ListingOut)
async def admin_promote_listing(listing_id: uuid.UUID, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    listing = await promote_listing(session, admin, listing_id)
    return await listing_out(session, listing)


@router.post("/admin/listings/{listing_id}/{action}", response_model=ListingOut)
async def admin_listing_publication(listing_id: uuid.UUID, action: str, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    if action not in {"publish", "unpublish"}:
        raise HTTPException(status_code=404, detail="Unknown listing action")
    listing = await set_listing_publication(session, admin, listing_id, action == "publish")
    return await listing_out(session, listing)


@router.get("/admin/deals", response_model=list[DealOut])
async def admin_deals(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(Deal).order_by(Deal.updated_at.desc()).limit(200))).all())


@router.post("/admin/deals/{deal_id}/resolve", response_model=DealOut)
async def admin_resolve_deal(
    deal_id: uuid.UUID,
    payload: DealResolution,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    deal = await resolve_dispute(session, admin, deal_id, payload.outcome, payload.reason)
    participants = list((await session.scalars(select(User).where(User.id.in_([deal.buyer_id, deal.seller_id]), User.bot_started.is_(True)))).all())
    for participant in participants:
        background_tasks.add_task(send_bot_notification, participant.telegram_id, "Администратор рассмотрел спор по сделке в AUTOFLOW MARKET")
    return deal


@router.get("/admin/conversations/{conversation_id}")
async def admin_conversation(conversation_id: uuid.UUID, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    conversation = await session.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    details = await conversation_details(session, conversation, admin, allow_admin=True)
    details["messages"] = [ConversationMessageOut.model_validate(item) for item in (await session.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id).order_by(ConversationMessage.created_at))).all()]
    return details


@router.get("/admin/withdrawals", response_model=list[AdminWithdrawalOut])
async def admin_withdrawals(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(WithdrawalRequest, User)
            .join(User, User.id == WithdrawalRequest.user_id)
            .order_by(WithdrawalRequest.created_at.desc())
        )
    ).all()

    return [
        AdminWithdrawalOut(
            **WithdrawalOut.model_validate(withdrawal).model_dump(),
            user_telegram_id=user.telegram_id,
            user_name=" ".join(
                filter(None, [user.first_name, user.last_name])
            ),
            user_username=user.username,
        )
        for withdrawal, user in rows
    ]

@router.post("/admin/withdrawals/{withdrawal_id}/{action}", response_model=WithdrawalOut)
async def admin_withdrawal_action(
    withdrawal_id: uuid.UUID,
    action: str,
    payload: WithdrawalDecision,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if action not in {"approve", "paid", "reject"}:
        raise HTTPException(status_code=404, detail="Unknown withdrawal action")
    withdrawal = await decide_withdrawal(session, admin, withdrawal_id, action, payload.reason)
    owner = await session.get(User, withdrawal.user_id)
    if owner and owner.bot_started:
        background_tasks.add_task(send_bot_notification, owner.telegram_id, f"Статус заявки на вывод изменён: {withdrawal.status}")
    return withdrawal


@router.get("/admin/users/{user_id}/financial-history")
async def admin_user_financial_history(user_id: uuid.UUID, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
    transactions = list((await session.scalars(select(WalletTransaction).where(WalletTransaction.user_id == user_id).order_by(WalletTransaction.created_at.desc()).limit(200))).all())
    payments = list((await session.scalars(select(StarPayment).where(StarPayment.user_id == user_id).order_by(StarPayment.created_at.desc()).limit(100))).all())
    withdrawals = list((await session.scalars(select(WithdrawalRequest).where(WithdrawalRequest.user_id == user_id).order_by(WithdrawalRequest.created_at.desc()).limit(100))).all())
    return {
        "user": {"id": str(user.id), "telegram_id": user.telegram_id, "name": " ".join(filter(None, [user.first_name, user.last_name]))},
        "wallet": WalletOut.model_validate(wallet),
        "wallet_transactions": [
            {"id": str(item.id), "type": item.transaction_type, "amount": item.amount, "description": item.description, "created_at": item.created_at}
            for item in transactions
        ],
        "star_payments": [
            {"id": str(item.id), "telegram_payment_charge_id": item.telegram_payment_charge_id, "xtr_amount": item.xtr_amount, "af_coin_amount": item.af_coin_amount, "status": item.status, "created_at": item.created_at}
            for item in payments
        ],
        "withdrawals": [WithdrawalOut.model_validate(item) for item in withdrawals],
    }


@router.post("/admin/balance-adjustments", response_model=WalletOut)
async def admin_balance_adjustment(
    payload: BalanceAdjustmentCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    return await adjust_balance(session, admin, payload)


@router.get("/notifications", response_model=list[NotificationOut])
async def notifications(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100))).all())


@router.post("/notifications/{notification_id}/read", status_code=204)
async def read_notification(notification_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    notification = await session.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read_at = datetime.now(UTC)
    await session.commit()


@router.get("/support/tickets", response_model=list[SupportTicketOut])
async def support_tickets(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tickets = list(
        (
            await session.scalars(
                select(SupportTicket)
                .where(or_(
                    SupportTicket.author_id == user.id,
                    SupportTicket.buyer_id == user.id,
                    SupportTicket.seller_id == user.id,
                ))
                .order_by(SupportTicket.updated_at.desc())
            )
        ).all()
    )
    return [await support_ticket_out(session, ticket) for ticket in tickets]


@router.post("/support/tickets", response_model=SupportTicketOut, status_code=201)
async def create_support_ticket(
    payload: SupportTicketCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        ticket = SupportTicket(
            user_id=user.id,
            author_id=user.id,
            case_type="general",
            topic=payload.topic.strip(),
            status="open",
            screenshot_url=payload.screenshot_url,
            unread_by_admin=True,
        )
        session.add(ticket)
        await session.flush()
        session.add(SupportMessage(ticket_id=ticket.id, sender_id=user.id, body=payload.message.strip()))
        administrators = list(
            (
                await session.scalars(
                    select(User).where(User.role == "admin", User.bot_started.is_(True))
                )
            ).all()
        )
        for administrator in administrators:
            await create_notification(
                session,
                administrator.id,
                "support_ticket",
                "Новое обращение в поддержку",
                payload.topic.strip(),
                {"ticket_id": str(ticket.id)},
            )
    for administrator in administrators:
        background_tasks.add_task(
            send_bot_notification,
            administrator.telegram_id,
            "Новое обращение в поддержку AUTOFLOW MARKET",
        )
    return await support_ticket_out(session, ticket)


@router.post("/support/tickets/{ticket_id}/messages", response_model=SupportMessageOut, status_code=201)
async def reply_to_support_ticket(
    ticket_id: uuid.UUID,
    payload: SupportReplyCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ticket = await session.get(SupportTicket, ticket_id)
    if not ticket or user.id not in {ticket.author_id, ticket.buyer_id, ticket.seller_id}:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    if ticket.status == "closed":
        raise HTTPException(status_code=409, detail="Закрытое обращение нельзя дополнить")
    if payload.client_request_id:
        existing = await session.scalar(select(SupportMessage).where(
            SupportMessage.ticket_id == ticket.id,
            SupportMessage.sender_id == user.id,
            SupportMessage.client_request_id == payload.client_request_id,
        ))
        if existing:
            return existing
    message = SupportMessage(
        ticket_id=ticket.id,
        sender_id=user.id,
        client_request_id=payload.client_request_id,
        body=payload.message.strip(),
    )
    ticket.status = "new" if ticket.case_type == "deal" else "open"
    ticket.unread_by_admin = True
    session.add(message)
    session.add(SupportCaseEvent(
        ticket_id=ticket.id,
        actor_id=user.id,
        event_type="participant_message",
        details={},
    ))
    administrators = list((await session.scalars(select(User).where(User.role == "admin"))).all())
    for administrator in administrators:
        await create_notification(
            session,
            administrator.id,
            "support_message",
            "Новое сообщение в обращении",
            payload.message.strip()[:240],
            {"ticket_id": str(ticket.id)},
        )
    await session.commit()
    await session.refresh(message)
    for administrator in administrators:
        if administrator.bot_started:
            background_tasks.add_task(send_bot_notification, administrator.telegram_id, "Новое сообщение в поддержке AUTOFLOW MARKET")
    return message


@router.get("/admin/support/tickets", response_model=list[SupportTicketOut])
async def admin_support_tickets(
    status_filter: str | None = Query(default=None, alias="status", pattern="^(new|open|in_progress|resolved|closed)$"),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    tickets = list(
        (
            await session.scalars(
                select(SupportTicket)
                .where(
                    SupportTicket.status.in_({"new", "open"})
                    if status_filter == "new"
                    else SupportTicket.status == status_filter
                    if status_filter
                    else True
                )
                .order_by(SupportTicket.unread_by_admin.desc(), SupportTicket.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )
    return [await support_ticket_out(session, ticket) for ticket in tickets]


@router.get("/admin/support/tickets/{ticket_id}", response_model=SupportTicketOut)
async def admin_support_ticket(
    ticket_id: uuid.UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    ticket = await session.scalar(select(SupportTicket).where(SupportTicket.id == ticket_id).with_for_update())
    if not ticket:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    ticket.unread_by_admin = False
    previous_status = ticket.status
    if ticket.status in {"new", "open"}:
        ticket.status = "in_progress"
    session.add(SupportCaseEvent(
        ticket_id=ticket.id,
        actor_id=admin.id,
        event_type="admin_opened",
        from_status=previous_status,
        to_status=ticket.status,
        details={},
    ))
    session.add(AdminAction(
        admin_id=admin.id,
        action="open_support_case",
        target_type="support_ticket",
        target_id=ticket.id,
    ))
    await session.commit()
    await session.refresh(ticket)
    return await support_ticket_out(session, ticket)


@router.post("/admin/support/tickets/{ticket_id}/messages", response_model=SupportMessageOut, status_code=201)
async def admin_reply_to_support_ticket(
    ticket_id: uuid.UUID,
    payload: SupportReplyCreate,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    ticket = await session.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    if payload.client_request_id:
        existing = await session.scalar(select(SupportMessage).where(
            SupportMessage.ticket_id == ticket.id,
            SupportMessage.sender_id == admin.id,
            SupportMessage.client_request_id == payload.client_request_id,
        ))
        if existing:
            return existing
    message = SupportMessage(
        ticket_id=ticket.id,
        sender_id=admin.id,
        client_request_id=payload.client_request_id,
        body=payload.message.strip(),
    )
    ticket.status = "in_progress"
    ticket.unread_by_admin = False
    session.add(message)
    session.add(SupportCaseEvent(
        ticket_id=ticket.id,
        actor_id=admin.id,
        event_type="admin_message",
        to_status="in_progress",
        details={},
    ))
    recipient_ids = {ticket.author_id}
    if ticket.case_type == "deal":
        recipient_ids.update({ticket.buyer_id, ticket.seller_id})
    recipient_ids.discard(None)
    for recipient_id in recipient_ids:
        await create_notification(
            session,
            recipient_id,
            "support_reply",
            "🛡 AutoFlow Support",
            payload.message.strip()[:240],
            {"ticket_id": str(ticket.id)},
        )
    await session.commit()
    await session.refresh(message)
    recipients = list((await session.scalars(select(User).where(User.id.in_(recipient_ids), User.bot_started.is_(True)))).all()) if recipient_ids else []
    for recipient in recipients:
        background_tasks.add_task(send_bot_notification, recipient.telegram_id, "🛡 AutoFlow Support ответила по вашему обращению")
    return message


@router.patch("/admin/support/tickets/{ticket_id}", response_model=SupportTicketOut)
async def update_support_ticket_status(
    ticket_id: uuid.UUID,
    payload: SupportStatusUpdate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    ticket = await session.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    if ticket.case_type == "deal" and payload.status in {"resolved", "closed"}:
        deal = await session.get(Deal, ticket.deal_id)
        if deal and deal.status == "disputed":
            raise HTTPException(status_code=409, detail="Сначала выберите финансовое решение по сделке")
    previous_status = ticket.status
    ticket.status = payload.status
    ticket.unread_by_admin = False
    if payload.status in {"resolved", "closed"}:
        ticket.resolved_at = datetime.now(UTC)
    session.add(SupportCaseEvent(
        ticket_id=ticket.id,
        actor_id=admin.id,
        event_type="status_changed",
        from_status=previous_status,
        to_status=payload.status,
        details={},
    ))
    session.add(
        AdminAction(
            admin_id=admin.id,
            action=f"support_{payload.status}",
            target_type="support_ticket",
            target_id=ticket.id,
        )
    )
    await session.commit()
    await session.refresh(ticket)
    return await support_ticket_out(session, ticket)


@router.post("/admin/support/tickets/{ticket_id}/resolve", response_model=SupportTicketOut)
async def resolve_support_ticket_financially(
    ticket_id: uuid.UUID,
    payload: SupportCaseResolution,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    ticket = await session.get(SupportTicket, ticket_id)
    if not ticket or ticket.case_type != "deal" or not ticket.deal_id:
        raise HTTPException(status_code=404, detail="Обращение по сделке не найдено")
    deal = await resolve_dispute(
        session,
        admin,
        ticket.deal_id,
        payload.outcome,
        payload.reason,
        support_ticket_id=ticket.id,
    )
    participants = list((await session.scalars(
        select(User).where(User.id.in_([deal.buyer_id, deal.seller_id]), User.bot_started.is_(True))
    )).all())
    for participant in participants:
        background_tasks.add_task(
            send_bot_notification,
            participant.telegram_id,
            "🛡 Поддержка AUTOFLOW MARKET приняла решение по сделке. Откройте приложение для подробностей.",
        )
    refreshed = await session.get(SupportTicket, ticket.id)
    return await support_ticket_out(session, refreshed)


@router.get("/profile", response_model=ProfileOut)
async def profile(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    wallet_value = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
    active = list((await session.scalars(select(Listing).where(Listing.seller_id == user.id, Listing.status.in_(["active", "reserved"])).order_by(Listing.created_at.desc()))).all())
    sold = list((await session.scalars(select(Listing).where(Listing.seller_id == user.id, Listing.status == "sold").order_by(Listing.sold_at.desc()))).all())
    purchase_deals = list((await session.scalars(select(Deal).where(Deal.buyer_id == user.id, Deal.status == "completed"))).all())
    purchases = [await session.get(Listing, item.listing_id) for item in purchase_deals]
    active_deals = list((await session.scalars(select(Deal).where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id), Deal.status.not_in(["completed", "cancelled"])))).all())
    conversation_values = list((await session.scalars(
        select(Conversation).where(
            or_(
                and_(Conversation.buyer_id == user.id, Conversation.buyer_hidden_at.is_(None)),
                and_(Conversation.seller_id == user.id, Conversation.seller_hidden_at.is_(None)),
            ),
            or_(Conversation.last_message_at.is_not(None), Conversation.deal_id.is_not(None)),
        ).order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc())
    )).all())
    transactions = list((await session.scalars(select(WalletTransaction).where(WalletTransaction.user_id == user.id).order_by(WalletTransaction.created_at.desc()).limit(100))).all())
    withdrawal_values = list((await session.scalars(select(WithdrawalRequest).where(WithdrawalRequest.user_id == user.id).order_by(WithdrawalRequest.created_at.desc()))).all())
    return ProfileOut(
        user=user,
        wallet=wallet_value,
        active_listings=[await listing_out(session, item, user.id) for item in active],
        sold_listings=[await listing_out(session, item, user.id) for item in sold],
        purchases=[await listing_out(session, item, user.id) for item in purchases if item],
        active_deals=active_deals,
        conversations=[await conversation_details(session, item, user) for item in conversation_values],
        wallet_transactions=[
            {
                "id": str(item.id),
                "type": item.transaction_type,
                "amount": item.amount,
                "available_before": item.available_before,
                "available_after": item.available_after,
                "frozen_before": item.frozen_before,
                "frozen_after": item.frozen_after,
                "description": item.description,
                "created_at": item.created_at,
            }
            for item in transactions
        ],
        withdrawals=withdrawal_values,
    )


@router.post("/telegram/webhook")
async def telegram_webhook(
    update: dict,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    expected_secret = settings.effective_telegram_webhook_secret
    if expected_secret and not hmac.compare_digest(x_telegram_bot_api_secret_token or "", expected_secret):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    pre_checkout = update.get("pre_checkout_query") or {}
    if pre_checkout.get("id"):
        sender = pre_checkout.get("from") or {}
        accepted, error_message = await validate_star_pre_checkout(
            session,
            int(sender.get("id") or 0),
            str(pre_checkout.get("invoice_payload") or ""),
            str(pre_checkout.get("currency") or ""),
            int(pre_checkout.get("total_amount") or 0),
        )
        await answer_pre_checkout_query(pre_checkout["id"], accepted, error_message)
        return {"ok": True}
    callback = update.get("callback_query") or {}
    if callback.get("id") and callback.get("data") in {"autoflow:how", "autoflow:start"}:
        callback_message = callback.get("message") or {}
        callback_sender = callback.get("from") or {}
        chat = callback_message.get("chat") or {}
        telegram_id = int(chat.get("id") or callback_sender.get("id") or 0)
        message_id = callback_message.get("message_id")
        await answer_bot_callback(str(callback["id"]))
        if telegram_id and message_id:
            await send_bot_menu(
                telegram_id,
                detailed=callback.get("data") == "autoflow:how",
                message_id=int(message_id),
            )
        return {"ok": True}
    message = update.get("message") or {}
    sender = message.get("from") or {}
    # Admin broadcasts are claimed by Telegram update_id and executed after the
    # webhook response. Telegram retries can therefore never start duplicates.
    if sender.get("id") in settings.admin_telegram_ids:
        text = parse_broadcast_command(message.get("text"))
        content_type = "text"
        photo_file_id = None
        if text is None and message.get("photo"):
            text = parse_broadcast_command(message.get("caption"))
            content_type = "photo"
            photo_file_id = str(message["photo"][-1]["file_id"])
        if text is not None:
            update_id = int(update.get("update_id") or 0)
            if not update_id:
                return {"ok": True, "accepted": False}
            if content_type == "text" and not text:
                background_tasks.add_task(
                    send_bot_notification,
                    int(sender["id"]),
                    "Добавьте текст после команды /рассылка или #рассылка.",
                )
                return {"ok": True, "accepted": False}
            broadcast_id = await create_admin_broadcast(
                session,
                telegram_update_id=update_id,
                admin_telegram_id=int(sender["id"]),
                content_type=content_type,
                text=text,
                photo_file_id=photo_file_id,
            )
            if broadcast_id is not None:
                background_tasks.add_task(run_admin_broadcast, broadcast_id)
            return {"ok": True, "accepted": broadcast_id is not None}
    start_text = str(message.get("text") or "").strip()
    if start_text.split(maxsplit=1)[0].split("@", 1)[0] == "/start" and sender.get("id"):
        start_payload = start_text.split(maxsplit=1)[1].strip() if len(start_text.split(maxsplit=1)) == 2 else None
        user = await session.scalar(select(User).where(User.telegram_id == int(sender["id"])))
        if not user:
            telegram_id = int(sender["id"])
            user = User(
                telegram_id=telegram_id,
                role="admin" if telegram_id in settings.admin_telegram_ids else "user",
                first_name=sender.get("first_name") or "Telegram User",
                last_name=sender.get("last_name"),
                username=sender.get("username"),
                bot_started=True,
            )
            session.add(user)
            await session.flush()
            session.add(Wallet(user_id=user.id))
        else:
            user.bot_started = True
        await session.commit()
        background_tasks.add_task(send_bot_menu, int(sender["id"]), start_payload=start_payload)
    payment = message.get("successful_payment")
    if payment and sender.get("id"):
        credited = await process_successful_payment(session, int(sender["id"]), payment)
        payment_intent = await session.scalar(
            select(StarPaymentIntent).where(
                StarPaymentIntent.invoice_payload == str(payment.get("invoice_payload") or "")
            )
        )
        payment_user = await session.scalar(select(User).where(User.telegram_id == int(sender["id"])))
        await session.commit()
        if credited and (not payment_intent or payment_intent.purpose != "training_checkout"):
            background_tasks.add_task(send_bot_notification, int(sender["id"]), f"Баланс AUTOFLOW MARKET пополнен на {payment['total_amount']} AF Coins")
        if payment_intent and payment_user and payment_intent.purpose == "training_checkout":
            try:
                completed_intent, purchase, created = await complete_training_payment_intent(
                    session,
                    payment_user,
                    payment_intent.id,
                    str(payment.get("telegram_payment_charge_id") or ""),
                )
            except HTTPException as exc:
                logger.error(
                    "training_checkout_completion_failed intent_id=%s status=%s detail=%s",
                    payment_intent.id,
                    exc.status_code,
                    str(exc.detail)[:300],
                )
                background_tasks.add_task(
                    send_bot_notification,
                    int(sender["id"]),
                    "Оплата получена, но заказ не удалось оформить автоматически. AF Coins сохранены на вашем балансе.",
                )
            else:
                if purchase and created:
                    if purchase.product_type == "automatic":
                        await begin_training_delivery(session, payment_user.id, purchase.id, cooldown_seconds=0)
                        background_tasks.add_task(
                            send_bot_notification,
                            int(sender["id"]),
                            "✅ Оплата получена.\nВаши материалы отправляются ниже.",
                        )
                        background_tasks.add_task(deliver_training_materials, purchase.id)
                    else:
                        background_tasks.add_task(
                            send_bot_notification,
                            int(sender["id"]),
                            "✅ Оплата получена.\nВаш заказ на персональное обучение принят. Администратор свяжется с вами в Telegram.",
                        )
                        background_tasks.add_task(notify_personal_training_admin, purchase.id)
        elif payment_intent and payment_user and payment_intent.purpose == "listing_checkout":
            completed_intent, deal, seller_telegram_id = await complete_listing_payment_intent(
                session, payment_user, payment_intent.id
            )
            if deal:
                if seller_telegram_id:
                    background_tasks.add_task(
                        send_bot_notification,
                        seller_telegram_id,
                        "Ваш товар хотят купить. Покупатель оплатил, деньги находятся под защитой. Откройте AUTOFLOW MARKET.",
                    )
                background_tasks.add_task(
                    send_bot_notification,
                    int(sender["id"]),
                    "Покупка оформлена. Деньги находятся под защитой до подтверждения получения.",
                )
            elif completed_intent.checkout_status == "listing_unavailable":
                background_tasks.add_task(
                    send_bot_notification,
                    int(sender["id"]),
                    "Объявление уже недоступно. Пополненные AF Coins сохранены на вашем балансе.",
                )
        elif credited and payment_intent and payment_user and payment_intent.purpose == "cart_checkout":
            current_cart_ids = {
                str(item)
                for item in (await session.scalars(select(CartItem.listing_id).where(CartItem.user_id == payment_user.id))).all()
            }
            expected_cart_ids = set((payment_intent.context or {}).get("listing_ids", []))
            await session.commit()
            try:
                if current_cart_ids != expected_cart_ids:
                    raise HTTPException(status_code=409, detail="Состав корзины изменился после выставления счёта")
                deals, seller_ids = await checkout_cart(session, payment_user)
            except HTTPException as error:
                await create_notification(
                    session,
                    payment_user.id,
                    "checkout_after_topup_failed",
                    "Покупка не завершена автоматически",
                    f"AF Coins сохранены на балансе: {error.detail}",
                )
                await session.commit()
            else:
                for telegram_id in seller_ids:
                    background_tasks.add_task(send_bot_notification, telegram_id, "Ваш товар хотят купить. Откройте AUTOFLOW MARKET, чтобы ответить покупателю")
                background_tasks.add_task(send_bot_notification, int(sender["id"]), f"Покупка оформлена. Создано сделок: {len(deals)}")
    return {"ok": True}
