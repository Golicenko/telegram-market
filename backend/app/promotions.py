"""Existing AF top-up economics, with durable reservations and server fulfillment."""
import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_CEILING

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlalchemy import or_, select

from .auth import get_current_user, require_admin
from .bot import call_bot_api
from .config import get_settings
from .database import AsyncSession, SessionLocal, get_session
from .models import Listing, ListingPromotion, Notification, PublicationDraft, StarPayment, StarPaymentIntent, User, Wallet
from .schemas import ListingCreate
from .services import (consume_purchase_hold, create_listing, hold_for_purchase, money,
                       process_successful_payment, release_purchase_hold, wallet_snapshot, wallet_transaction)

router = APIRouter(prefix="/api", tags=["VIP"])
logger = logging.getLogger("autoflow.promotions")
PREFIX = "autoflow_vip:"


def parts(order):
    return tuple(Decimal(order.funding.get(key, "0")) for key in ("purchased", "earned", "bonus"))


def set_parts(order, values):
    order.funding = dict(zip(("purchased", "earned", "bonus"), map(str, values)))


def quote_values(available):
    settings = get_settings()
    cost = money(settings.listing_promotion_cost_af_coins)
    balance = min(cost, money(available))
    # The existing top-up service credits exactly one purchased AF per XTR.
    stars = int((cost - balance).to_integral_value(rounding=ROUND_CEILING))
    return {"cost_af": cost, "balance_af": balance, "stars": stars,
            "duration_hours": settings.listing_promotion_hours, "af_per_star": 1,
            "rounding_credit_af": money(stars - (cost - balance))}


def output(order, intent=None, *, admin=False):
    result = {key: getattr(order, key) for key in ("id", "listing_id", "cost_af", "balance_af", "stars", "duration_hours",
        "status", "created_at", "paid_at", "pinned_until", "expires_at", "last_error")}
    result.update(number=str(order.id), invoice_url=intent.invoice_link if intent else None, af_per_star=1)
    result["listing_payload"] = order.listing_payload
    if admin:
        result.update(user_id=order.user_id, payment_id=order.payment_id, ledger_id=order.ledger_id)
    return result


class Start(BaseModel):
    request_id: uuid.UUID
    listing_id: uuid.UUID | None = None
    listing_payload: ListingCreate | None = None

    @model_validator(mode="after")
    def one_target(self):
        if bool(self.listing_id) == bool(self.listing_payload):
            raise ValueError("Specify one listing or publication draft")
        if self.listing_payload and (not self.listing_payload.client_request_id or not self.listing_payload.promote_for_24h):
            raise ValueError("A pinned publication with a request ID is required")
        return self


@router.get("/vip/quote")
async def quote(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id))
    return quote_values(wallet.available_balance if wallet else 0)


async def start_order(session, user, payload):
    target = str(payload.listing_id) if payload.listing_id else f"draft:{payload.listing_payload.client_request_id}"
    saved = payload.listing_payload.model_dump(mode="json") if payload.listing_payload else None
    async with session.begin():
        # Serializes requests from two devices, including the first insert.
        await session.scalar(select(User.id).where(User.id == user.id).with_for_update(key_share=True))
        old = await session.scalar(select(ListingPromotion).where(ListingPromotion.user_id == user.id,
            ListingPromotion.request_id == payload.request_id))
        if old:
            if old.target_key != target or old.listing_payload != saved:
                raise HTTPException(409, "Идентификатор запроса уже используется")
            return old
        active = await session.scalar(select(ListingPromotion).where(ListingPromotion.user_id == user.id,
            ListingPromotion.target_key == target, ListingPromotion.status.in_(("awaiting_payment", "paid"))))
        if active:
            if active.listing_payload != saved:
                raise HTTPException(409, "Откройте ранее сохранённую оплату VIP")
            return active
        if payload.listing_id:
            listing = await session.get(Listing, payload.listing_id)
            if not listing or listing.seller_id != user.id:
                raise HTTPException(404, "Объявление не найдено")
            if listing.status != "active" or listing.deleted_at is not None:
                raise HTTPException(409, "Можно закрепить только активное объявление")
            if listing.pinned and listing.pinned_until and listing.pinned_until > datetime.now(UTC):
                raise HTTPException(409, "Объявление уже закреплено")
        else:
            # A VIP invoice cannot bypass the separate publication Stars fee.
            draft = await session.scalar(select(PublicationDraft).where(PublicationDraft.user_id == user.id,
                PublicationDraft.request_id == payload.listing_payload.client_request_id))
            if draft and draft.payload != saved:
                raise HTTPException(409, "Сохранённый черновик отличается")
            if not (draft and draft.payment_id and draft.status in ("paid", "review")):
                from .publication_quota import require_free_slot
                await require_free_slot(session, user)
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id).with_for_update())
        if not wallet:
            raise HTTPException(409, "Кошелёк не найден")
        values = quote_values(wallet.available_balance)
        if values["stars"] > get_settings().star_topup_max:
            raise HTTPException(409, "Доплата превышает разрешённый размер счёта")
        now = datetime.now(UTC)
        order = ListingPromotion(id=uuid.uuid4(), user_id=user.id, request_id=payload.request_id,
            target_key=target, listing_id=payload.listing_id, listing_payload=saved,
            cost_af=values["cost_af"], balance_af=values["balance_af"], stars=values["stars"],
            duration_hours=values["duration_hours"], status="awaiting_payment" if values["stars"] else "paid",
            expires_at=now + timedelta(minutes=30), paid_at=None if values["stars"] else now)
        before = wallet_snapshot(wallet)
        funding = hold_for_purchase(wallet, order.balance_af) if order.balance_af else (Decimal(0),) * 3
        set_parts(order, funding)
        wallet.version += 1
        session.add(wallet_transaction(wallet, "vip_reservation", -order.balance_af, *before,
            "Временный резерв AF для VIP, не окончательное списание", external_reference=f"vip:{order.id}:reserve", funding=funding))
        if order.stars:
            intent = StarPaymentIntent(id=uuid.uuid4(), user_id=user.id, invoice_payload=PREFIX + str(order.id),
                xtr_amount=order.stars, purpose="listing_promotion_topup", status="pending", checkout_status="pending",
                context={"promotion_id": str(order.id)}, expires_at=order.expires_at)
            session.add(intent)
            await session.flush()
            order.intent_id = intent.id
        session.add(order)
    return order


async def invoice(session, order_id):
    async with session.begin():
        order = await session.scalar(select(ListingPromotion).where(ListingPromotion.id == order_id).with_for_update())
        if not order or order.status != "awaiting_payment":
            return
        intent = await session.get(StarPaymentIntent, order.intent_id)
        if not intent.invoice_link:
            # Only the persisted link can be paid: an ambiguous createInvoiceLink
            # response exposes no second link to the user.
            data = await call_bot_api("createInvoiceLink", {"title": "VIP-закрепление AutoFlow",
                "description": f"Доплата за VIP на {order.duration_hours} ч. Зарезервировано {order.balance_af} AF.",
                "payload": intent.invoice_payload, "provider_token": "", "currency": "XTR",
                "prices": [{"label": "Доплата VIP", "amount": order.stars}]})
            intent.invoice_link = str(data["result"])


def record_balance_pin(session, listing, wallet, cost, funding, entry):
    """Audit the unchanged, atomic initial-publish and legacy AF-only endpoints."""
    now = datetime.now(UTC)
    entry.id = entry.id or uuid.uuid4()
    session.add(ListingPromotion(user_id=wallet.user_id, request_id=uuid.uuid4(), target_key=str(listing.id),
        listing_id=listing.id, cost_af=cost, balance_af=cost, stars=0, duration_hours=get_settings().listing_promotion_hours,
        funding=dict(zip(("purchased", "earned", "bonus"), map(str, funding))), ledger_id=entry.id,
        status="completed", expires_at=now, paid_at=now, pinned_until=listing.pinned_until))


async def finish_locked(session, order, listing, wallet):
    """Caller holds order and listing; consume all funding and pin in ONE commit."""
    before = wallet_snapshot(wallet)
    funding = parts(order)
    if money(sum(funding)) != money(order.cost_af):
        raise HTTPException(409, "Сумма резерва VIP не совпадает")
    consume_purchase_hold(wallet, *funding)
    wallet.version += 1
    now = datetime.now(UTC)
    listing.pinned, listing.pinned_until = True, now + timedelta(hours=order.duration_hours)
    entry = wallet_transaction(wallet, "listing_promotion", -order.cost_af, *before,
        f"VIP {order.id} до {listing.pinned_until.isoformat()}", external_reference=f"vip:{order.id}:complete", funding=funding)
    entry.id = uuid.uuid4()
    session.add(entry)
    order.status, order.listing_id, order.pinned_until, order.ledger_id = "completed", listing.id, listing.pinned_until, entry.id
    order.last_error = None
    if order.intent_id:
        intent = await session.get(StarPaymentIntent, order.intent_id)
        intent.checkout_status = "completed"
    session.add(Notification(user_id=order.user_id, notification_type="vip_completed", title="VIP-закрепление успешно оплачено",
        body=f"Объявление закреплено до {listing.pinned_until.isoformat()}", payload={"listing_id": str(listing.id), "promotion_id": str(order.id)}, delivery_status="pending"))


async def restore_locked(session, order, reason):
    wallet = await session.scalar(select(Wallet).where(Wallet.user_id == order.user_id).with_for_update())
    before = wallet_snapshot(wallet)
    funding = parts(order)
    release_purchase_hold(wallet, *funding)
    wallet.version += 1
    session.add(wallet_transaction(wallet, "vip_reservation_released", sum(funding), *before, reason,
        external_reference=f"vip:{order.id}:release", funding=funding))
    set_parts(order, (Decimal(0),) * 3)
    order.status = "restored" if order.payment_id else "cancelled"
    order.last_error = reason
    if order.intent_id:
        intent = await session.get(StarPaymentIntent, order.intent_id)
        if intent.status == "pending":
            intent.status = "expired"  # A delayed successful_payment must still be recorded/credited.
        intent.checkout_status = "failed"
    if order.payment_id:
        session.add(Notification(user_id=order.user_id, notification_type="vip_restored", title="VIP не активирован",
            body=reason + " AF возвращены на баланс, включая подтверждённую доплату Stars по действующему курсу.",
            payload={"promotion_id": str(order.id)}, delivery_status="pending"))


async def fulfill(session, order_id):
    order = await session.get(ListingPromotion, order_id)
    if not order or order.status != "paid":
        await session.rollback()
        return
    payload, user_id = order.listing_payload, order.user_id
    publication_id = None
    if payload:
        draft = await session.scalar(select(PublicationDraft).where(PublicationDraft.user_id == user_id,
            PublicationDraft.request_id == uuid.UUID(payload["client_request_id"]), PublicationDraft.payment_id.is_not(None),
            PublicationDraft.status.in_(("paid", "review"))))
        publication_id = draft.id if draft else None
    user = await session.get(User, user_id)
    await session.commit()
    try:
        if payload:
            await create_listing(session, user, ListingCreate.model_validate(payload), listing_type="regular", pinned=True,
                publication_id=publication_id, promotion_id=order_id)
        else:
            async with session.begin():
                order = await session.scalar(select(ListingPromotion).where(ListingPromotion.id == order_id).with_for_update().execution_options(populate_existing=True))
                if order.status != "paid":
                    return
                listing = await session.scalar(select(Listing).where(Listing.id == order.listing_id).with_for_update())
                if user.is_blocked or not listing or listing.seller_id != user.id or listing.status != "active" or listing.deleted_at or (listing.pinned and listing.pinned_until and listing.pinned_until > datetime.now(UTC)):
                    await restore_locked(session, order, "Объявление уже закреплено или недоступно.")
                    return
                wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id).with_for_update())
                await finish_locked(session, order, listing, wallet)
    except HTTPException as exc:
        await session.rollback()
        async with session.begin():
            order = await session.scalar(select(ListingPromotion).where(ListingPromotion.id == order_id).with_for_update().execution_options(populate_existing=True))
            if order.status == "paid":
                await restore_locked(session, order, "Закрепление не выполнено: условия публикации изменились.")
        logger.warning("vip_restored order=%s status=%s", order_id, exc.status_code)
    except Exception as exc:
        await session.rollback()
        # Paid receipt + reservation already committed. A restarted worker retries.
        logger.warning("vip_fulfillment_retry order=%s error_type=%s", order_id, type(exc).__name__)


async def validate_checkout(session, telegram_id, payload, currency, amount, query_id):
    async with session.begin():
        try:
            order_id = uuid.UUID(payload.removeprefix(PREFIX))
        except ValueError:
            return False, "Счёт VIP не найден"
        order = await session.scalar(select(ListingPromotion).where(ListingPromotion.id == order_id).with_for_update())
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if not order or not user or user.is_blocked or order.user_id != user.id or order.status != "awaiting_payment" or currency != "XTR" or order.stars != amount or order.expires_at <= datetime.now(UTC):
            return False, "Счёт VIP недоступен. Откройте закрепление снова."
        intent = await session.get(StarPaymentIntent, order.intent_id)
        prior = (intent.context or {}).get("checkout_query_id")
        if prior and prior != query_id:
            return False, "Этот счёт уже обрабатывается"
        intent.context = {**(intent.context or {}), "checkout_query_id": query_id}
        return True, None


async def receive_payment(session, telegram_id, payment):
    if payment.get("is_test") or payment.get("currency") != "XTR" or not payment.get("telegram_payment_charge_id"):
        raise HTTPException(400, "Invalid VIP payment")
    try:
        order_id = uuid.UUID(str(payment.get("invoice_payload", "")).removeprefix(PREFIX))
    except ValueError:
        raise HTTPException(400, "Invalid VIP invoice") from None
    async with session.begin():
        order = await session.scalar(select(ListingPromotion).where(ListingPromotion.id == order_id).with_for_update().execution_options(populate_existing=True))
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if not order or not user or order.user_id != user.id or order.stars != payment.get("total_amount"):
            raise HTTPException(400, "VIP payment mismatch")
        charge = payment["telegram_payment_charge_id"]
        previous = await session.scalar(select(StarPayment).where(StarPayment.telegram_payment_charge_id == charge))
        if previous:
            if previous.user_id != user.id or previous.raw_payload.get("invoice_payload") != payment["invoice_payload"]:
                raise HTTPException(409, "Payment identity mismatch")
            return order_id
        if order.payment_id:
            # A different real charge is evidence, not a duplicate webhook. Refund
            # it with the supported Telegram API; never pay for VIP twice.
            session.add(StarPayment(user_id=user.id, telegram_payment_charge_id=charge,
                xtr_amount=order.stars, af_coin_amount=0, status="vip_extra_refund", raw_payload=payment))
            return order_id
        await process_successful_payment(session, telegram_id, payment, _within_transaction=True)
        await session.flush()
        receipt = await session.scalar(select(StarPayment).where(StarPayment.telegram_payment_charge_id == charge))
        order.payment_id, order.paid_at = receipt.id, datetime.now(UTC)
        if order.status != "awaiting_payment":
            order.status = "restored"
            order.last_error = "Поздняя оплата отменённого VIP сохранена в AF на балансе. Повторного списания нет."
            return order_id
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user.id).with_for_update())
        missing = money(order.cost_af - order.balance_af)
        before = wallet_snapshot(wallet)
        # Specifically reserve the purchased AF from this receipt; do not change
        # the provenance of previously held bonus/earned balances.
        wallet.purchased_balance = money(wallet.purchased_balance - missing)
        wallet.purchased_frozen_balance = money(wallet.purchased_frozen_balance + missing)
        wallet.version += 1
        funding = parts(order)
        set_parts(order, (funding[0] + missing, funding[1], funding[2]))
        session.add(wallet_transaction(wallet, "vip_topup_reserved", -missing, *before,
            "Подтверждённая доплата зарезервирована для VIP", external_reference=f"vip:{order.id}:topup-hold"))
        order.status = "paid"
    return order_id


@router.post("/vip/orders")
async def start(payload: Start, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    order = await start_order(session, user, payload)
    await invoice(session, order.id)
    await fulfill(session, order.id)
    return await get_order(order.id, user, session)


@router.get("/vip/orders")
async def orders(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.scalars(select(ListingPromotion).where(ListingPromotion.user_id == user.id)
        .order_by(ListingPromotion.created_at.desc()).limit(30))).all()
    return [output(row) for row in rows]


@router.get("/vip/orders/{order_id}")
async def get_order(order_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    order = await session.get(ListingPromotion, order_id, populate_existing=True)
    if not order or order.user_id != user.id:
        raise HTTPException(404, "VIP не найден")
    return output(order, await session.get(StarPaymentIntent, order.intent_id) if order.intent_id else None)


@router.post("/vip/orders/{order_id}/cancel")
async def cancel(order_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    async with session.begin():
        order = await session.scalar(select(ListingPromotion).where(ListingPromotion.id == order_id).with_for_update())
        if not order or order.user_id != user.id:
            raise HTTPException(404, "VIP не найден")
        if order.status == "awaiting_payment":
            await restore_locked(session, order, "Оплата отменена. Резерв AF освобождён.")
    return output(order)


@router.get("/admin/vip/orders")
async def admin_orders(limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    rows = (await session.scalars(select(ListingPromotion).order_by(ListingPromotion.created_at.desc(), ListingPromotion.id)
        .limit(limit + 1).offset(offset))).all()
    items = []
    for row in rows[:limit]:
        item = output(row, admin=True)
        receipt = await session.get(StarPayment, row.payment_id) if row.payment_id else None
        item["telegram_payment_charge_id"] = receipt.telegram_payment_charge_id if receipt else None
        items.append(item)
    return {"items": items, "has_more": len(rows) > limit}


async def recover_once():
    async with SessionLocal() as session:
        ids = (await session.scalars(select(ListingPromotion.id).where(or_(ListingPromotion.status == "paid",
            (ListingPromotion.status == "awaiting_payment") & (ListingPromotion.expires_at < datetime.now(UTC))))
            .order_by(ListingPromotion.updated_at).limit(100))).all()
    for order_id in ids:
        async with SessionLocal() as session:
            async with session.begin():
                order = await session.scalar(select(ListingPromotion).where(ListingPromotion.id == order_id).with_for_update())
                if order.status == "awaiting_payment" and order.expires_at < datetime.now(UTC):
                    await restore_locked(session, order, "Срок счёта истёк. Резерв AF освобождён.")
            await fulfill(session, order_id)
    async with SessionLocal() as session:
        ids = (await session.scalars(select(StarPayment.id).where(StarPayment.status == "vip_extra_refund").limit(100))).all()
        await session.rollback()
        for receipt_id in ids:
            async with session.begin():
                receipt = await session.scalar(select(StarPayment).where(StarPayment.id == receipt_id).with_for_update())
                if receipt.status != "vip_extra_refund":
                    continue
                user = await session.get(User, receipt.user_id)
                try:
                    await call_bot_api("refundStarPayment", {"user_id": user.telegram_id, "telegram_payment_charge_id": receipt.telegram_payment_charge_id})
                except HTTPException as error:
                    if "CHARGE_ALREADY_REFUNDED" not in str(error.detail):
                        raise
                receipt.status = "vip_extra_refunded"


async def run_worker():
    while True:
        try:
            await recover_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("vip_recovery_failed error_type=%s", type(exc).__name__)
        await asyncio.sleep(30)
