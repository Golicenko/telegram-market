"""Read-only training sales, based on purchase snapshots and the wallet ledger."""
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, and_, case, cast, func, or_, select

from .admin_operations import date_window
from .auth import require_admin
from .database import AsyncSession, get_session
from .models import StarPayment, TrainingPurchase, User, WalletTransaction
from .withdrawal_support import profile_url

router = APIRouter(prefix="/api/admin/training-analytics", tags=["training analytics"])


def confirmed_purchase():
    # Never multiply a purchase by its delivery attempts, materials or ledger rows.
    debit = select(WalletTransaction.id).where(
        WalletTransaction.related_training_purchase_id == TrainingPurchase.id,
        WalletTransaction.user_id == TrainingPurchase.buyer_id,
        WalletTransaction.transaction_type.in_(("training_purchase", "training_purchase_reserved")),
        WalletTransaction.amount == -TrainingPurchase.price_af_coins,
    ).exists()
    receipt = select(StarPayment.id).where(
        StarPayment.telegram_payment_charge_id == TrainingPurchase.telegram_payment_charge_id,
        StarPayment.user_id == TrainingPurchase.buyer_id,
        StarPayment.status == "credited",
        StarPayment.raw_payload["is_test"].astext.is_distinct_from("true"),
    ).exists()
    return and_(TrainingPurchase.payment_status == "paid", or_(debit, receipt))


def sales_projection():
    refunds = select(WalletTransaction.related_training_purchase_id.label("purchase_id"),
        WalletTransaction.user_id.label("buyer_id"), func.sum(WalletTransaction.amount).label("amount"),
        func.max(WalletTransaction.created_at).label("refunded_at")).where(
            WalletTransaction.related_training_purchase_id.is_not(None),
            WalletTransaction.transaction_type.in_(("training_refund", "training_purchase_refund")),
            WalletTransaction.amount > 0,
        ).group_by(WalletTransaction.related_training_purchase_id, WalletTransaction.user_id).subquery()
    confirmed = confirmed_purchase()
    refund = func.coalesce(refunds.c.amount, 0)
    payment_state = case((~confirmed, "unverified"), (refund >= TrainingPurchase.price_af_coins, "refunded"),
                         (refund > 0, "partially_refunded"), else_="paid")
    return select(TrainingPurchase.id, TrainingPurchase.product_id, TrainingPurchase.buyer_id,
        TrainingPurchase.title_snapshot.label("title"), TrainingPurchase.buyer_display_name.label("buyer_name"),
        TrainingPurchase.buyer_username, TrainingPurchase.buyer_telegram_id,
        TrainingPurchase.created_at.label("purchased_at"), TrainingPurchase.price_af_coins.label("amount_af"),
        TrainingPurchase.product_type, TrainingPurchase.status.label("fulfillment_status"), TrainingPurchase.delivery_status,
        case((TrainingPurchase.telegram_payment_charge_id.is_not(None), "stars_to_af"), else_="af_balance").label("payment_method"),
        confirmed.label("confirmed"), payment_state.label("payment_status"), refund.label("refund_af"),
        refunds.c.refunded_at,
    ).outerjoin(refunds, and_(refunds.c.purchase_id == TrainingPurchase.id, refunds.c.buyer_id == TrainingPurchase.buyer_id)).subquery()


async def report_data(session, *, start=None, end=None, timezone="Europe/Bratislava", product_id=None,
                      payment_status=None, buyer=None, search=None, limit=25, offset=0, now=None, all_time=False):
    now = now or datetime.now(UTC)
    # Validates timezone and inclusive calendar dates, including DST boundaries.
    lower, upper = date_window(start, end, timezone, now=now)
    today = now.astimezone(ZoneInfo(timezone)).date()
    today_start, _ = date_window(today, today, timezone, now=now)
    week_start, _ = date_window(today - timedelta(days=6), today, timezone, now=now)
    month_start, _ = date_window(today - timedelta(days=29), today, timezone, now=now)
    sales = sales_projection()
    common = []
    if product_id:
        common.append(sales.c.product_id == product_id)
    if payment_status:
        common.append(sales.c.payment_status == payment_status)
    if buyer:
        term = "%" + buyer.strip().lstrip('@').replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
        common.append(or_(sales.c.buyer_username.ilike(term, escape="\\"), sales.c.buyer_name.ilike(term, escape="\\"),
            cast(sales.c.buyer_telegram_id, String) == buyer.strip(), cast(sales.c.buyer_id, String) == buyer.strip()))
    if search:
        term = "%" + search.strip().lstrip('#@').replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
        common.append(or_(sales.c.title.ilike(term, escape="\\"), sales.c.buyer_username.ilike(term, escape="\\"),
            sales.c.buyer_name.ilike(term, escape="\\"), cast(sales.c.buyer_telegram_id, String) == search.strip(),
            cast(sales.c.id, String).ilike(term, escape="\\")))
    period = common if all_time else [*common, sales.c.purchased_at >= lower, sales.c.purchased_at < upper]

    def totals(conditions):
        return select(func.count().filter(sales.c.confirmed).label("paid_count"),
            func.count().filter(~sales.c.confirmed).label("unverified_count"),
            func.coalesce(func.sum(sales.c.amount_af).filter(sales.c.confirmed), 0).label("gross_af"),
            func.coalesce(func.sum(sales.c.refund_af).filter(sales.c.confirmed), 0).label("refund_af"),
            func.count(func.distinct(sales.c.buyer_id)).filter(sales.c.confirmed).label("unique_buyers"),
        ).where(*conditions)

    summary = dict((await session.execute(totals(period))).one()._mapping)
    summary["net_af"] = summary["gross_af"] - summary["refund_af"]
    counts = dict((await session.execute(select(
        func.count().filter(and_(sales.c.confirmed, sales.c.purchased_at >= today_start)).label("today"),
        func.count().filter(and_(sales.c.confirmed, sales.c.purchased_at >= week_start)).label("week"),
        func.count().filter(and_(sales.c.confirmed, sales.c.purchased_at >= month_start)).label("month"),
        func.count().filter(sales.c.confirmed).label("all_time"),
    ).where(*common, sales.c.purchased_at <= now))).one()._mapping)
    total = await session.scalar(select(func.count()).select_from(sales).where(*period))
    rows = (await session.execute(select(sales).where(*period).order_by(sales.c.purchased_at.desc(), sales.c.id.desc())
        .limit(limit).offset(offset))).all()
    users = {u.id: u for u in (await session.scalars(select(User).where(User.id.in_({r.buyer_id for r in rows})))).all()} if rows else {}
    items = []
    for row in rows:
        item = dict(row._mapping)
        user = users.get(row.buyer_id)
        item["number"] = str(row.id)  # Full stable UUID, not a collision-prone truncated number.
        item["profile_url"] = profile_url(user) if user else None
        item["buyer_username"] = user.username if user else row.buyer_username
        items.append(item)
    products = (await session.execute(select(sales.c.product_id,
        func.max(sales.c.title).label("title"),
        func.count().filter(and_(sales.c.confirmed, sales.c.purchased_at >= today_start)).label("today"),
        func.count().filter(and_(sales.c.confirmed, sales.c.purchased_at >= week_start)).label("week"),
        func.count().filter(and_(sales.c.confirmed, sales.c.purchased_at >= month_start)).label("month"),
        func.count().filter(sales.c.confirmed).label("all_time"),
        func.coalesce(func.sum(sales.c.amount_af).filter(sales.c.confirmed), 0).label("gross_af"),
        func.coalesce(func.sum(sales.c.refund_af).filter(sales.c.confirmed), 0).label("refund_af"),
    ).where(*common, sales.c.purchased_at <= now).group_by(sales.c.product_id).order_by(sales.c.product_id)
        .limit(limit + 1).offset(offset))).all()
    return {"items": items, "total": total, "has_more": offset + len(items) < total,
        "summary": summary, "counts": counts, "products": [dict(row._mapping) for row in products[:limit]],
        "products_has_more": len(products) > limit, "timezone": timezone,
        "from_utc": lower, "until_utc_exclusive": upper,
        "definitions": ["Продажи подтверждены списанием AF или подтверждённым Stars-платежом. Неоплаченные счета не входят.",
            "Возвраты — только связанные с покупкой записи возврата в ledger. Несвязанные ручные корректировки нельзя восстановить автоматически.",
            "Суммы за выбранный период относятся к покупкам этого периода, включая последующие возвраты. Сегодня/7/30 дней — календарные дни выбранной зоны; всего — вся сохранённая история.",
            "Исторические записи без доказательства оплаты показаны как «Нет подтверждения», но не увеличивают продажи."]}


@router.get("")
async def report(start: date | None = None, end: date | None = None,
    timezone: str = Query(default="Europe/Bratislava", max_length=64), product_id: uuid.UUID | None = None,
    payment_status: str | None = Query(default=None, pattern="^(paid|refunded|partially_refunded|unverified)$"),
    buyer: str | None = Query(default=None, max_length=128), search: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0, le=100000), all_time: bool = False,
    admin: User = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return await report_data(session, start=start, end=end, timezone=timezone, product_id=product_id,
        payment_status=payment_status, buyer=buyer, search=search, limit=limit, offset=offset, all_time=all_time)
