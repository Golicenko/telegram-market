"""Exactly 5 XTR / 24h. No AF credit or referral rewards for a pin payment."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .account_sales import ready
from .account_video import router
from .auth import get_current_user
from .bot import call_bot_api
from .database import AsyncSession, get_session
from .models import AccountPin, Listing, Notification, StarPayment, User

PREFIX = "autoflow_account_pin:"


class PinStart(BaseModel):
    request_id: uuid.UUID


@router.post("/account-products/{listing_id}/pin")
async def start_pin(
    listing_id: uuid.UUID,
    payload: PinStart,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ready()
    async with session.begin():
        await session.scalar(
            select(User.id).where(User.id == user.id).with_for_update(key_share=True)
        )
        item = await session.scalar(
            select(Listing).where(Listing.id == listing_id).with_for_update()
        )
        if not item or item.seller_id != user.id or item.product_kind != "account":
            raise HTTPException(404, "Аккаунт не найден")
        old = await session.scalar(
            select(AccountPin).where(
                AccountPin.user_id == user.id,
                AccountPin.request_id == payload.request_id,
            )
        )
        if old:
            if old.listing_id != listing_id:
                raise HTTPException(
                    409, "Идентификатор использован для другого аккаунта"
                )
            return {
                "id": old.id,
                "invoice_url": old.invoice_url,
                "status": old.status,
                "stars": 5,
                "hours": 24,
            }
        if (
            item.status != "active"
            or item.deleted_at
            or (item.pinned_until and item.pinned_until > datetime.now(UTC))
        ):
            raise HTTPException(409, "Аккаунт уже закреплён или недоступен")
        active = await session.scalar(
            select(AccountPin)
            .where(AccountPin.listing_id == listing_id, AccountPin.status == "pending")
            .order_by(AccountPin.created_at.desc())
            .limit(1)
        )
        if active and active.created_at > datetime.now(UTC) - timedelta(minutes=30):
            return {
                "id": active.id,
                "invoice_url": active.invoice_url,
                "status": active.status,
                "stars": 5,
                "hours": 24,
            }
        if active:
            active.status = "expired"
        order = AccountPin(
            id=uuid.uuid4(),
            listing_id=item.id,
            user_id=user.id,
            request_id=payload.request_id,
        )
        session.add(order)
        # A bounded Bot API call under this row lock prevents duplicate invoices.
        result = await call_bot_api(
            "createInvoiceLink",
            {
                "title": "VIP аккаунта на 24 часа",
                "description": "Закрепление одного аккаунта в AutoFlow Market. Не пополнение AF.",
                "payload": PREFIX + str(order.id),
                "currency": "XTR",
                "prices": [{"label": "VIP 24 часа", "amount": 5}],
            },
        )
        order.invoice_url = result["result"]
    return {
        "id": order.id,
        "invoice_url": order.invoice_url,
        "status": order.status,
        "stars": 5,
        "hours": 24,
    }


@router.get("/account-pins/{pin_id}")
async def pin_status(
    pin_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    order = await session.get(AccountPin, pin_id)
    if not order or order.user_id != user.id:
        raise HTTPException(404, "Оплата не найдена")
    return {"id": order.id, "status": order.status}


async def validate_checkout(session, telegram_id, payload, currency, amount, query_id):
    try:
        order_id = uuid.UUID(payload.removeprefix(PREFIX))
    except ValueError:
        return False, "Счёт не найден"
    async with session.begin():
        order = await session.scalar(
            select(AccountPin)
            .where(AccountPin.id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        item = await session.get(Listing, order.listing_id) if order else None
        if (
            not order
            or not user
            or user.is_blocked
            or order.user_id != user.id
            or currency != "XTR"
            or amount != 5
            or order.status != "pending"
            or not item
            or item.status != "active"
            or item.deleted_at
            or order.created_at < datetime.now(UTC) - timedelta(minutes=30)
        ):
            return False, "Счёт недоступен или сумма не совпадает"
        if (
            order.checkout_query_id
            and order.checkout_query_id != query_id
            and order.checkout_at > datetime.now(UTC) - timedelta(minutes=15)
        ):
            return False, "Предыдущая оплата ещё проверяется"
        order.checkout_query_id, order.checkout_at = query_id, datetime.now(UTC)
    return True, None


async def receive_payment(session, telegram_id, payment):
    if (
        payment.get("is_test")
        or payment.get("currency") != "XTR"
        or type(payment.get("total_amount")) is not int
        or payment["total_amount"] != 5
        or not payment.get("telegram_payment_charge_id")
    ):
        raise HTTPException(400, "Оплата VIP не подтверждена")
    try:
        order_id = uuid.UUID(
            str(payment.get("invoice_payload", "")).removeprefix(PREFIX)
        )
    except ValueError:
        raise HTTPException(400, "Неизвестный счёт") from None
    async with session.begin():
        snapshot = await session.get(AccountPin, order_id)
        if not snapshot:
            raise HTTPException(404, "Счёт не найден")
        item = await session.scalar(
            select(Listing).where(Listing.id == snapshot.listing_id).with_for_update()
        )
        order = await session.scalar(
            select(AccountPin)
            .where(AccountPin.id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if not user or order.user_id != user.id:
            raise HTTPException(403, "Владелец счёта не совпадает")
        charge = payment["telegram_payment_charge_id"]
        previous = await session.scalar(
            select(StarPayment).where(StarPayment.telegram_payment_charge_id == charge)
        )
        if previous:
            if (
                previous.user_id != user.id
                or previous.raw_payload.get("invoice_payload")
                != payment["invoice_payload"]
            ):
                raise HTTPException(409, "Платёж уже использован")
            return
        activate = bool(
            not order.payment_id
            and order.status == "pending"
            and item
            and item.status == "active"
            and not item.deleted_at
        )
        receipt = StarPayment(
            user_id=user.id,
            telegram_payment_charge_id=charge,
            xtr_amount=5,
            af_coin_amount=0,
            status="account_vip" if activate else "account_vip_refund_pending",
            raw_payload=payment,
            processed_at=datetime.now(UTC),
        )
        session.add(receipt)
        await session.flush()
        if not order.payment_id:
            order.payment_id = receipt.id
            order.status = "completed" if activate else "refund_pending"
        if activate:
            item.pinned = True
            item.pinned_until = max(
                item.pinned_until or datetime.now(UTC), datetime.now(UTC)
            ) + timedelta(hours=24)
            session.add(
                Notification(
                    user_id=user.id,
                    notification_type="vip_completed",
                    title="Аккаунт закреплён",
                    body="VIP аккаунта действует 24 часа.",
                    payload={"listing_id": str(item.id)},
                    delivery_status="pending",
                )
            )


async def refund_once(session):
    async with session.begin():
        receipt = await session.scalar(
            select(StarPayment)
            .where(StarPayment.status == "account_vip_refund_pending")
            .order_by(StarPayment.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if not receipt:
            return
        user = await session.get(User, receipt.user_id)
        try:
            await call_bot_api(
                "refundStarPayment",
                {
                    "user_id": user.telegram_id,
                    "telegram_payment_charge_id": receipt.telegram_payment_charge_id,
                },
            )
        except HTTPException as error:
            if "CHARGE_ALREADY_REFUNDED" not in str(error.detail):
                raise
        receipt.status = "account_vip_refunded"
        order = await session.scalar(
            select(AccountPin).where(AccountPin.payment_id == receipt.id)
        )
        if order and order.status == "refund_pending":
            order.status = "refunded"
        session.add(
            Notification(
                user_id=user.id,
                notification_type="publication_refunded",
                title="VIP: возврат",
                body="За недоступное закрепление аккаунта возвращено 5 Stars.",
                payload={},
                delivery_status="pending",
            )
        )
