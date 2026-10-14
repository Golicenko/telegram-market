"""Stars publication orders. Never credit AF or invoke referral commission."""
import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from .auth import get_current_user, require_admin
from .bot import call_bot_api
from .database import AsyncSession, SessionLocal, get_session
from .models import AdminAction, Listing, Notification, PublicationDraft, PublicationRules, StarPayment, User
from .schemas import ListingCreate

router = APIRouter(prefix="/api")
logger = logging.getLogger("autoflow.publications")
PREFIX = "autoflow_publish:"


def output(draft):
    return {"id": str(draft.id), "status": draft.status, "price_stars": draft.price_stars,
            "invoice_url": draft.invoice_url, "listing_id": str(draft.listing_id) if draft.listing_id else None,
            "last_error": draft.last_error, "payload": draft.payload}


async def rules_out(session, user):
    from .publication_quota import publication_rules
    return await publication_rules(session, user)


@router.get("/publication-rules")
async def get_rules(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return await rules_out(session, user)


class RulesUpdate(BaseModel):
    free_limit: int = Field(ge=0, le=10000)
    price_stars: int = Field(ge=1, le=10000)
    enabled: bool
    reason: str = Field(min_length=3, max_length=300)


@router.put("/admin/publication-rules")
async def update_rules(payload: RulesUpdate, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    async with session.begin():
        # Serialize initial creation as well as subsequent edits.
        from sqlalchemy import text
        await session.execute(text("SELECT pg_advisory_xact_lock(74190829)"))
        rules = await session.get(PublicationRules, 1)
        before = {key: getattr(rules, key) for key in ("free_limit", "price_stars", "enabled")} if rules else {"free_limit": 5, "price_stars": 5, "enabled": True}
        if not rules:
            rules = PublicationRules(id=1)
            session.add(rules)
        values = payload.model_dump(exclude={"reason"})
        for key, value in values.items():
            setattr(rules, key, value)
        session.add(AdminAction(admin_id=admin.id, action="publication_rules", target_type="settings", reason=payload.reason, metadata_json={"before": before, "after": values}))
    return await rules_out(session, admin)


@router.get("/publication-drafts")
async def list_drafts(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.scalars(select(PublicationDraft).where(PublicationDraft.user_id == user.id, PublicationDraft.status != "published").order_by(PublicationDraft.created_at.desc()).limit(30))).all()
    return [output(row) for row in rows]


@router.post("/publication-drafts")
async def create_draft(payload: ListingCreate, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    if not payload.client_request_id:
        raise HTTPException(422, "Требуется идентификатор публикации")
    async with session.begin():
        locked_user = await session.scalar(select(User).where(User.id == user.id).with_for_update(key_share=True).execution_options(populate_existing=True))
        draft = await session.scalar(select(PublicationDraft).where(PublicationDraft.user_id == user.id, PublicationDraft.request_id == payload.client_request_id))
        if draft:
            if draft.payload != payload.model_dump(mode="json"):
                raise HTTPException(409, "Этот платёж связан с сохранённым черновиком. Откройте его в форме публикации.")
            return output(draft)
        existing = await session.scalar(select(Listing.id).where(Listing.seller_id == user.id, Listing.client_request_id == payload.client_request_id))
        if existing:
            raise HTTPException(409, "Объявление уже опубликовано")
        rules = await rules_out(session, locked_user)
        if not rules["payment_required"]:
            raise HTTPException(409, "Доступна бесплатная публикация. Повторите публикацию.")
        if payload.promote_for_24h:
            from .models import Wallet
            from .config import get_settings
            from .services import money
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
            available = money(wallet.available_balance if wallet else 0)
            required = money(get_settings().listing_promotion_cost_af_coins)
            if available < required:
                raise HTTPException(402, {"code": "insufficient_af_coins", "purpose": "listing_promotion",
                    "message": "Недостаточно AF Coins для выбранного закрепления", "available_af_coins": str(available),
                    "required_af_coins": str(required), "missing_af_coins": str(required - available)})
        draft = PublicationDraft(user_id=user.id, request_id=payload.client_request_id, payload=payload.model_dump(mode="json"), price_stars=rules["price_stars"])
        session.add(draft)
        await session.flush()
    return output(draft)


async def owned(session, draft_id, user, lock=False):
    query = select(PublicationDraft).where(PublicationDraft.id == draft_id, PublicationDraft.user_id == user.id)
    draft = await session.scalar(query.with_for_update() if lock else query)
    if not draft:
        raise HTTPException(404, "Черновик не найден")
    return draft


@router.post("/publication-drafts/{draft_id}/invoice")
async def invoice(draft_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    async with session.begin():
        draft = await owned(session, draft_id, user, True)
        if draft.status != "draft":
            return output(draft)
        if not draft.invoice_url:
            data = await call_bot_api("createInvoiceLink", {
                "title": "Размещение объявления", "description": "Публикация одного объявления в AutoFlow Market. Не пополнение AF.",
                "payload": PREFIX + str(draft.id), "currency": "XTR",
                "prices": [{"label": "Публикация", "amount": draft.price_stars}],
            })
            draft.invoice_url = str(data["result"])
    return output(draft)


@router.get("/publication-drafts/{draft_id}")
async def get_draft(draft_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return output(await owned(session, draft_id, user))


async def validate_checkout(session, telegram_id, payload, currency, amount, query_id):
    try:
        draft_id = uuid.UUID(payload.removeprefix(PREFIX))
    except ValueError:
        return False, "Счёт не найден"
    async with session.begin():
        draft = await session.scalar(select(PublicationDraft).where(PublicationDraft.id == draft_id).with_for_update())
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if not draft or not user or user.is_blocked or draft.user_id != user.id or currency != "XTR" or draft.price_stars != amount:
            return False, "Сумма или владелец счёта не совпадает"
        if draft.status != "draft":
            return False, "Оплата уже получена"
        # A single accepted checkout at a time, including two devices/copies.
        now = datetime.now(UTC)
        if draft.checkout_query_id and draft.checkout_query_id != query_id and draft.checkout_at > now - timedelta(minutes=15):
            return False, "Предыдущий платёж ещё проверяется. Повторите позже."
        draft.checkout_query_id, draft.checkout_at = query_id, now
    return True, None


async def receive_payment(session, telegram_id, payment):
    if payment.get("is_test") or payment.get("currency") != "XTR":
        raise HTTPException(400, "Недопустимый платёж")
    try:
        draft_id = uuid.UUID(str(payment.get("invoice_payload", "")).removeprefix(PREFIX))
    except ValueError:
        raise HTTPException(400, "Счёт не найден")
    charge = str(payment.get("telegram_payment_charge_id") or "")
    if not charge:
        raise HTTPException(400, "Отсутствует идентификатор платежа")
    async with session.begin():
        draft = await session.scalar(select(PublicationDraft).where(PublicationDraft.id == draft_id).with_for_update())
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if not draft or not user or draft.user_id != user.id or payment.get("total_amount") != draft.price_stars:
            raise HTTPException(400, "Платёж не соответствует черновику")
        existing = await session.scalar(select(StarPayment).where(StarPayment.telegram_payment_charge_id == charge))
        if existing:
            if existing.user_id != user.id or existing.raw_payload.get("invoice_payload") != payment.get("invoice_payload"):
                raise HTTPException(409, "Платёж уже использован")
            return draft.id
        receipt = StarPayment(user_id=user.id, telegram_payment_charge_id=charge, provider_payment_charge_id=payment.get("provider_payment_charge_id"),
                              xtr_amount=draft.price_stars, af_coin_amount=0, status="publication", raw_payload=payment, processed_at=datetime.now(UTC))
        session.add(receipt)
        await session.flush()
        if draft.payment_id or draft.status == "published":
            # Extremely delayed second Telegram charge is retained for admin refund,
            # never discarded or converted to AF and never creates a second listing.
            receipt.status = "publication_review"
            await alert_admins(session, draft, "Telegram прислал дополнительный платёж. Нужен возврат лишнего платежа через поддержку.", receipt.id)
        else:
            draft.payment_id, draft.status = receipt.id, "paid"
            draft.retry_at = datetime.now(UTC)
    return draft.id


async def alert_admins(session, draft, body, payment_id=None):
    for admin in (await session.scalars(select(User).where(User.role == "admin"))).all():
        session.add(Notification(user_id=admin.id, notification_type="publication_review", title="Проверка оплаченной публикации", body=body,
                                 payload={"publication_id": str(draft.id), "payment_id": str(payment_id or draft.payment_id)}, delivery_status="pending"))


async def fulfill(session, draft_id):
    from .services import create_listing
    draft = await session.get(PublicationDraft, draft_id)
    if not draft or draft.status != "paid":
        await session.rollback()
        return
    user = await session.get(User, draft.user_id)
    saved_payload = draft.payload
    await session.commit()
    try:
        payload = ListingCreate.model_validate(saved_payload)
        await create_listing(session, user, payload, listing_type="regular", pinned=payload.promote_for_24h, publication_id=draft_id)
    except Exception as error:
        await session.rollback()
        async with session.begin():
            draft = await session.scalar(select(PublicationDraft).where(PublicationDraft.id == draft_id).with_for_update().execution_options(populate_existing=True))
            if draft.status != "paid":
                return
            draft.attempts += 1
            draft.last_error = "Оплата сохранена. Публикация ожидает повторной обработки. Если выбрано закрепление, проверьте баланс AF."
            draft.retry_at = datetime.now(UTC) + timedelta(minutes=min(60, 2 ** min(draft.attempts, 6)))
            if draft.attempts >= 5:
                draft.status = "review"
                await alert_admins(session, draft, "Оплата получена, публикация не завершена. Проверьте черновик; повторная оплата не нужна.")
        logger.warning("publication_retry draft=%s error_type=%s", draft_id, type(error).__name__)


@router.post("/publication-drafts/{draft_id}/retry")
async def retry(draft_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    draft = await owned(session, draft_id, user)
    await session.commit()
    if draft.status == "paid":
        await fulfill(session, draft_id)
    return output(await owned(session, draft_id, user))


@router.get("/admin/publication-drafts")
async def admin_drafts(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    rows = (await session.scalars(select(PublicationDraft).where(PublicationDraft.status.in_(["paid", "review", "refund_pending"])).order_by(PublicationDraft.created_at).limit(100))).all()
    return [output(row) for row in rows]


@router.get("/admin/publication-extra-payments")
async def extra_payments(admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    rows = (await session.scalars(select(StarPayment).where(StarPayment.status.in_(["publication_review", "publication_extra_refund"])).order_by(StarPayment.created_at).limit(100))).all()
    return [{"id": str(row.id), "price_stars": row.xtr_amount, "status": row.status} for row in rows]


class Resolution(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/admin/publication-extra-payments/{payment_id}/refund")
async def refund_extra(payment_id: uuid.UUID, payload: Resolution, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    async with session.begin():
        receipt = await session.scalar(select(StarPayment).where(StarPayment.id == payment_id).with_for_update())
        if not receipt or receipt.status not in {"publication_review", "publication_extra_refund", "publication_extra_refunded"}:
            raise HTTPException(409, "Дополнительный платёж не найден")
        if receipt.status == "publication_extra_refunded":
            return {"status": receipt.status}
        if receipt.status != "publication_extra_refund":
            session.add(AdminAction(admin_id=admin.id, action="publication_extra_refund", target_type="payment", target_id=receipt.id, reason=payload.reason))
        receipt.status = "publication_extra_refund"
    await complete_extra_refund(session, payment_id)
    return {"status": "publication_extra_refunded"}


async def complete_extra_refund(session, payment_id):
    async with session.begin():
        receipt = await session.scalar(select(StarPayment).where(StarPayment.id == payment_id).with_for_update().execution_options(populate_existing=True))
        if not receipt or receipt.status != "publication_extra_refund":
            return
        user = await session.get(User, receipt.user_id)
        try:
            await call_bot_api("refundStarPayment", {"user_id": user.telegram_id, "telegram_payment_charge_id": receipt.telegram_payment_charge_id})
        except HTTPException as error:
            if "CHARGE_ALREADY_REFUNDED" not in str(error.detail):
                raise
        receipt.status = "publication_extra_refunded"
        session.add(Notification(user_id=user.id, notification_type="publication_refunded", title="Возврат дополнительной оплаты", body=f"Возвращён дополнительный платёж {receipt.xtr_amount} ⭐ за публикацию.", payload={}, delivery_status="pending"))


@router.post("/admin/publication-drafts/{draft_id}/retry")
async def admin_retry(draft_id: uuid.UUID, payload: Resolution, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    async with session.begin():
        draft = await session.scalar(select(PublicationDraft).where(PublicationDraft.id == draft_id).with_for_update().execution_options(populate_existing=True))
        if not draft or draft.status not in {"review", "paid"} or not draft.payment_id:
            raise HTTPException(409, "Нет ожидающей оплаченной публикации")
        draft.status, draft.attempts = "paid", 0
        session.add(AdminAction(admin_id=admin.id, action="publication_retry", target_type="publication", target_id=draft.id, reason=payload.reason))
    await fulfill(session, draft_id)
    return output(await session.get(PublicationDraft, draft_id))


@router.post("/admin/publication-drafts/{draft_id}/refund")
async def admin_refund(draft_id: uuid.UUID, payload: Resolution, admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    # Persist the intent before calling Telegram, retry the same charge after crash.
    async with session.begin():
        draft = await session.scalar(select(PublicationDraft).where(PublicationDraft.id == draft_id).with_for_update().execution_options(populate_existing=True))
        if not draft or not draft.payment_id or draft.status not in {"paid", "review", "refund_pending", "refunded"}:
            raise HTTPException(409, "Возврат недоступен для опубликованного объявления")
        if draft.status == "refunded":
            return output(draft)
        if draft.status != "refund_pending":
            session.add(AdminAction(admin_id=admin.id, action="publication_refund_requested", target_type="publication", target_id=draft.id, reason=payload.reason))
        draft.status = "refund_pending"
    await refund_pending(session, draft_id)
    return output(await session.get(PublicationDraft, draft_id))


async def refund_pending(session, draft_id):
    async with session.begin():
        draft = await session.scalar(select(PublicationDraft).where(PublicationDraft.id == draft_id).with_for_update().execution_options(populate_existing=True))
        if draft.status != "refund_pending":
            return
        receipt = await session.get(StarPayment, draft.payment_id)
        user = await session.get(User, draft.user_id)
        try:
            await call_bot_api("refundStarPayment", {"user_id": user.telegram_id, "telegram_payment_charge_id": receipt.telegram_payment_charge_id})
        except HTTPException as error:
            # Telegram's already-refunded error is an idempotent recovery result.
            if "CHARGE_ALREADY_REFUNDED" not in str(error.detail):
                raise
        draft.status, receipt.status = "refunded", "publication_refunded"
        session.add(Notification(user_id=user.id, notification_type="publication_refunded", title="Публикация: возврат", body=f"Возвращено {draft.price_stars} ⭐ за неопубликованное объявление.", payload={}, delivery_status="pending"))


async def run_publication_worker():
    while True:
        try:
            async with SessionLocal() as session:
                ids = list((await session.scalars(select(PublicationDraft.id).where(
                    or_(PublicationDraft.status == "refund_pending", (PublicationDraft.status == "paid") & (PublicationDraft.retry_at <= datetime.now(UTC))))
                    .order_by(PublicationDraft.created_at).limit(30))).all())
                await session.commit()
                for draft_id in ids:
                    try:
                        await fulfill(session, draft_id)
                        await session.commit()
                        await refund_pending(session, draft_id)
                    except Exception as error:
                        await session.rollback()
                        logger.warning("publication_recovery_failed draft=%s error_type=%s", draft_id, type(error).__name__)
                extra_ids = list((await session.scalars(select(StarPayment.id).where(StarPayment.status == "publication_extra_refund").limit(30))).all())
                await session.commit()
                for payment_id in extra_ids:
                    try:
                        await complete_extra_refund(session, payment_id)
                    except Exception as error:
                        await session.rollback()
                        logger.warning("publication_extra_refund_failed payment=%s error_type=%s", payment_id, type(error).__name__)
        except Exception as error:
            logger.warning("publication_worker_failed error_type=%s", type(error).__name__)
        await asyncio.sleep(60)
