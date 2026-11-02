"""Owner-only, read-only projections. Units never cross an implicit exchange rate.

Ledger facts and one-to-one payment records, not notification/delivery attempts.
No accounting entries, balances, statuses or external payments are changed here.
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Numeric, String, and_, cast, func, literal, select, text, union_all

from .admin_access import require_owner
from .admin_operations import date_window
from .database import AsyncSession, get_session
from .models import (Deal, PublicationDraft, Referral, ReferralReward, StarPayment,
                     TrainingPurchase, User, Wallet, WalletTransaction, WithdrawalRequest)
from .training_analytics import confirmed_purchase
from .withdrawal_support import profile_url, validated_username

router = APIRouter(prefix="/api/admin/finance", tags=["owner-finance"])

LABELS = {
    "car_turnover": "Оплаченные автомобили — оборот, не доход платформы",
    "training_turnover": "Оплаченные обучения — оборот",
    "publication": "Опубликованные платные объявления",
    "vip": "VIP и продления — окончательное списание AF",
    "car_commission": "Комиссия завершённых сделок",
    "owner_car": "Завершённые продажи автомобилей владельца",
    "training_platform": "Обучение — доля платформы после расчёта",
    "training_author": "Обучение — зачислено другим авторам",
    "training_owner": "Обучение — зачислено владельцу как автору",
    "withdrawal_fee": "Комиссия исполненных выводов",
    "stars_received": "Подтверждённые поступления Stars — не прибыль",
    "stars_returned_cohort": "Возвращённые Stars из поступлений периода (не дата возврата)",
    "withdrawal_stars": "Завершённые ручные выплаты Stars",
    "car_refund": "Возвраты покупателям автомобилей",
    "training_refund": "Возвраты покупателям обучения",
    "referral_bonus": "Зачислены невыводимые реферальные бонусы",
    "adjustment": "Корректировки AF администратором",
}


def amount(value):
    return format(Decimal(value or 0).quantize(Decimal("0.01")), "f")


def operations(owner_id):
    """Disjoint classifications; turnover/receipts are never added to income."""
    wt, training, payment = WalletTransaction, TrainingPurchase, StarPayment
    def row(kind, model, timestamp, value, user, *conditions, unit="AF", category="detail", identity=None):
        return select(literal(kind).label("kind"), cast(identity if identity is not None else model.id, String).label("reference"),
            timestamp.label("at"), cast(value, Numeric(20, 2)).label("amount"), literal(unit).label("unit"),
            literal(category).label("category"), user.label("user_id")).where(timestamp.is_not(None), *conditions)

    # A refunded training order cannot silently keep earning commission. There is
    # no authoritative commission-reversal allocation for partial refunds yet.
    training_refund = select(wt.id).where(wt.related_training_purchase_id == training.id,
        wt.user_id == training.buyer_id, wt.amount > 0,
        wt.transaction_type.in_(("training_refund", "training_purchase_refund"))).exists()
    author_credit = select(wt.id).where(wt.related_training_purchase_id == training.id,
        wt.user_id == training.seller_id, wt.transaction_type == "training_sale",
        wt.amount == training.seller_payout).exists()
    paid_receipt = payment.raw_payload["is_test"].astext.is_distinct_from("true")
    known_receipt = payment.status.in_(("credited", "publication", "publication_review", "publication_extra_refund",
        "publication_extra_refunded", "publication_refunded", "vip_extra_refund", "vip_extra_refunded"))
    returned = payment.status.in_(("publication_extra_refunded", "publication_refunded", "vip_extra_refunded"))
    paid_at = func.coalesce(payment.processed_at, payment.created_at)
    pub = row("publication", payment, paid_at, payment.xtr_amount, payment.user_id,
        payment.status == "publication", paid_receipt, PublicationDraft.status == "published",
        PublicationDraft.user_id == payment.user_id, PublicationDraft.price_stars == payment.xtr_amount,
        unit="Stars", category="platform_income").join(PublicationDraft, PublicationDraft.payment_id == payment.id)
    owner_income = row("owner_car", wt, wt.created_at, wt.amount, wt.user_id,
        wt.transaction_type == "sale_income", wt.user_id == owner_id, wt.amount >= 0,
        Deal.seller_id == owner_id, Deal.status == "completed", category="owner_income").join(Deal, Deal.id == wt.related_deal_id)
    withdrawal_fee = row("withdrawal_fee", wt, wt.created_at, WithdrawalRequest.fee_af, wt.user_id,
        wt.transaction_type == "withdrawal_paid", wt.amount == -WithdrawalRequest.amount,
        wt.user_id == WithdrawalRequest.user_id, WithdrawalRequest.status == "paid", WithdrawalRequest.fee_af.is_not(None),
        category="platform_income").join(WithdrawalRequest, WithdrawalRequest.id == wt.related_withdrawal_id)
    referral_credit = row("referral_bonus", ReferralReward, ReferralReward.created_at, wt.amount, ReferralReward.user_id,
        wt.user_id == ReferralReward.user_id, wt.amount == ReferralReward.amount,
        wt.transaction_type.in_(("referral_milestone", "referral_commission")), category="bonus_issued"
        ).join(wt, wt.id == ReferralReward.transaction_id)
    return union_all(
        # Both single and cart checkout create one Deal with a persisted paid
        # snapshot and deadline. Legacy cart holds have no individual deal FK.
        row("car_turnover", Deal, Deal.created_at, Deal.price_af_coins, Deal.buyer_id,
            Deal.status != "pending_payment", Deal.frozen_amount > 0, Deal.seller_response_deadline.is_not(None), category="turnover"),
        row("training_turnover", training, training.created_at, training.price_af_coins, training.buyer_id,
            confirmed_purchase(), category="turnover"),
        pub,
        row("vip", wt, wt.created_at, -wt.amount, wt.user_id, wt.transaction_type == "listing_promotion", wt.amount < 0, category="platform_income"),
        row("car_commission", wt, wt.created_at, -wt.amount, wt.user_id,
            wt.transaction_type == "platform_commission", wt.related_deal_id.is_not(None), wt.amount <= 0, category="platform_income"),
        owner_income,
        row("training_platform", training, training.settled_at, training.platform_commission, training.seller_id,
            confirmed_purchase(), author_credit, ~training_refund, category="platform_income"),
        row("training_owner", wt, wt.created_at, wt.amount, wt.user_id,
            wt.transaction_type == "training_sale", wt.user_id == owner_id, wt.related_training_purchase_id.is_not(None), category="owner_income"),
        row("training_author", wt, wt.created_at, wt.amount, wt.user_id,
            wt.transaction_type == "training_sale", wt.user_id != owner_id, wt.related_training_purchase_id.is_not(None)),
        withdrawal_fee,
        row("stars_received", payment, paid_at, payment.xtr_amount, payment.user_id, paid_receipt, known_receipt,
            unit="Stars", category="receipt"),
        row("stars_returned_cohort", payment, paid_at, payment.xtr_amount, payment.user_id, paid_receipt, returned,
            unit="Stars", category="returned_cohort"),
        row("withdrawal_stars", WithdrawalRequest, WithdrawalRequest.paid_at, WithdrawalRequest.payout_stars, WithdrawalRequest.user_id,
            WithdrawalRequest.status == "paid", WithdrawalRequest.payout_stars.is_not(None), unit="Stars", category="recorded_payout"),
        row("car_refund", wt, wt.created_at, wt.amount, wt.user_id, wt.related_deal_id.is_not(None), wt.amount > 0,
            wt.transaction_type.in_(("refund", "seller_timeout_refund", "dispute_refund")), category="refund"),
        row("training_refund", wt, wt.created_at, wt.amount, wt.user_id, wt.related_training_purchase_id.is_not(None), wt.amount > 0,
            wt.transaction_type.in_(("training_refund", "training_purchase_refund")), category="refund"),
        referral_credit,
        row("adjustment", wt, wt.created_at, wt.amount, wt.user_id, wt.transaction_type == "admin_adjustment", category="adjustment"),
    ).subquery("financial_operations")


DEFINITIONS = [
    "Все суммы AF и Stars независимы. Пересчёта в евро нет. Пополнения — поступления и обязательства, не прибыль.",
    "30% — комиссия текущего вывода, не пополнения. В доход включена только сохранённая fee_af исполненного вывода с ledger-списанием; исторические NULL не восстановлены по новой формуле.",
    "Оборот AF: оплаченные автомобили с серверным сроком и подтверждённые покупки обучения, до возвратов. Публикации Stars показаны отдельно.",
    "Доход платформы: выполненный VIP, опубликованные платные объявления, рассчитанные комиссии. Продажи владельца показаны отдельно и не прибавляются повторно к обороту.",
    "Обучение: оборот, доля платформы и зачисления авторам разделены. Если найден возврат обучения, его комиссия исключена до сверки (частичное распределение не выдумывается).",
    "График — текущая проекция признанного дохода по датам исходных операций, не банковский денежный поток. Для всего времени свыше 366 дней используются месяцы.",
    "Возвраты AF показаны по ledger-дате. Для возвратов Stars нет отдельного надёжного timestamp: показана сумма возвращённых платежей когорты поступлений периода, не возвраты, совершённые в этом периоде.",
    "Ручные выплаты Stars подтверждены записью администратора, а не независимой выпиской Telegram. Частично отправленные подарки ещё открытых заявок не входят в завершённые выплаты.",
    "Обязательства — снимок всех кошельков сейчас, включая escrow/резервы. Открытые заявки — детализация этих резервов, не дополнительное слагаемое. Бонусы выделены отдельно, не считаются выводимыми.",
    "Нет расходов на хостинг, стоимости приобретения/конвертации Stars, налогов, внешних выплат владельцу и полного учёта затрат. Чистая прибыль и фактически полученные евро неизвестны; ноль не подставляется.",
    "Ledger, оплаты, оборот и распределение дохода — разные виды операций одной цепочки. Строки таблицы нельзя просто суммировать. UUID — техническая ссылка для аудита; charge_id и raw payment payload не передаются.",
]


async def report_data(session, owner_id, *, start=None, end=None, timezone="Europe/Bratislava", all_time=False, limit=25, offset=0, now=None):
    now = now or datetime.now(UTC)
    lower, upper = date_window(start, end, timezone, now)
    op = operations(owner_id)
    if all_time:
        lower = await session.scalar(select(func.min(op.c.at))) or lower
        upper = now
    conditions = [op.c.at >= lower, op.c.at < upper]
    grouped = (await session.execute(select(op.c.kind, op.c.unit, op.c.category, func.count().label("count"),
        func.sum(op.c.amount).label("amount")).where(*conditions).group_by(op.c.kind, op.c.unit, op.c.category))).all()
    sources = [{"key": r.kind, "label": LABELS[r.kind], "unit": r.unit, "category": r.category,
                "count": r.count, "amount": amount(r.amount)} for r in grouped]
    def total(category, unit):
        return amount(sum((Decimal(r["amount"]) for r in sources if r["category"] == category and r["unit"] == unit), Decimal(0)))
    grain = "month" if (upper-lower).days > 366 else "day"
    bucket = func.date_trunc(grain, func.timezone(timezone, op.c.at))
    daily = (await session.execute(select(bucket.label("day"), op.c.unit, func.sum(op.c.amount).label("amount"))
        .where(*conditions, op.c.category == "platform_income").group_by(bucket, op.c.unit).order_by(bucket, op.c.unit))).all()
    # Keep calendar spacing, including dates with no recognized income.
    values = {(r.day.date(), r.unit): r.amount for r in daily}
    first, last = lower.astimezone(ZoneInfo(timezone)).date(), (upper-timedelta(microseconds=1)).astimezone(ZoneInfo(timezone)).date()
    cursor = first.replace(day=1) if grain == "month" else first
    chart = []
    while cursor <= last:
        chart.extend({"day": cursor, "unit": unit, "amount": amount(values.get((cursor, unit), 0))} for unit in ("AF", "Stars"))
        cursor = (date(cursor.year+1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month+1, 1)) if grain == "month" else cursor+timedelta(days=1)
    rows = (await session.execute(select(op).where(*conditions).order_by(op.c.at.desc(), op.c.kind, op.c.reference)
        .limit(limit+1).offset(offset))).mappings().all()
    balances = (await session.execute(select(*[func.coalesce(func.sum(getattr(Wallet, field)), 0).label(field) for field in
        ("purchased_balance", "earned_balance", "bonus_balance", "purchased_frozen_balance", "earned_frozen_balance", "bonus_frozen_balance")]))).one()._mapping
    pending = (await session.execute(select(func.count().label("count"), func.coalesce(func.sum(WithdrawalRequest.amount), 0).label("af"),
        func.coalesce(func.sum(WithdrawalRequest.fee_af), 0).label("fees_af"),
        func.coalesce(func.sum(WithdrawalRequest.payout_stars), 0).label("stars"),
        func.count().filter(WithdrawalRequest.fee_af.is_(None)).label("missing_fee_count"))
        .where(WithdrawalRequest.status.in_(("pending", "approved"))))).one()
    unknown_paid = await session.scalar(select(func.count()).select_from(WithdrawalRequest).where(WithdrawalRequest.status == "paid",
        WithdrawalRequest.paid_at >= lower, WithdrawalRequest.paid_at < upper, WithdrawalRequest.fee_af.is_(None)))
    pub_pending = await session.scalar(select(func.coalesce(func.sum(PublicationDraft.price_stars), 0)).where(
        PublicationDraft.payment_id.is_not(None), PublicationDraft.status.in_(("paid", "review", "refund_pending"))))
    unverified = await session.scalar(select(func.count()).select_from(TrainingPurchase).where(
        TrainingPurchase.created_at >= lower, TrainingPurchase.created_at < upper, ~confirmed_purchase()))
    return {"timezone": timezone, "from_utc": lower, "until_utc_exclusive": upper, "generated_at": now,
        "summary": {"turnover_af": total("turnover", "AF"), "publication_income_stars": total("platform_income", "Stars"),
            "platform_income_af": total("platform_income", "AF"), "owner_income_af": total("owner_income", "AF"),
            "stars_received": total("receipt", "Stars"), "stars_returned_from_receipts_cohort": total("returned_cohort", "Stars"),
            "recorded_payout_stars": total("recorded_payout", "Stars"), "refund_af": total("refund", "AF"),
            "bonus_issued_af": total("bonus_issued", "AF"), "net_profit": None, "external_owner_receipts": None,
            "net_label": "Расчётная прибыль без неучтённых расходов: недостаточно данных о расходах"},
        "liabilities_now": {"wallets_af": {key: amount(value) for key, value in balances.items()},
            "withdrawals": {"count": pending.count, "reserved_af": amount(pending.af), "expected_fee_af": amount(pending.fees_af),
                "expected_stars": pending.stars, "missing_fee_count": pending.missing_fee_count},
            "unfulfilled_publications_stars": pub_pending},
        "data_quality": {"paid_withdrawals_without_fee": unknown_paid, "unverified_training_purchases": unverified},
        "sources": sources, "chart": {"grain": grain, "items": chart},
        "operations": [{**dict(row), "label": LABELS[row["kind"]], "amount": amount(row["amount"])} for row in rows[:limit]],
        "has_more": len(rows) > limit, "offset": offset, "limit": limit, "definitions": DEFINITIONS}


async def referral_leaders(session):
    # Aggregate each relation/reward independently BEFORE joining User. Never
    # multiply referral counts by the number of payments or milestones.
    counts = select(Referral.referrer_id.label("user_id"), func.count().label("qualified")).where(
        Referral.qualified_at.is_not(None)).group_by(Referral.referrer_id).subquery()
    earned = select(ReferralReward.user_id, func.sum(ReferralReward.amount).label("accrued")).group_by(ReferralReward.user_id).subquery()
    credited = select(ReferralReward.user_id, func.sum(WalletTransaction.amount).label("credited")).join(
        WalletTransaction, and_(WalletTransaction.id == ReferralReward.transaction_id, WalletTransaction.user_id == ReferralReward.user_id,
        WalletTransaction.amount == ReferralReward.amount, WalletTransaction.transaction_type.in_(("referral_milestone", "referral_commission"))))
    credited = credited.group_by(ReferralReward.user_id).subquery()
    rows = (await session.execute(select(User, counts.c.qualified, earned.c.accrued, credited.c.credited)
        .join(counts, counts.c.user_id == User.id).outerjoin(earned, earned.c.user_id == User.id).outerjoin(credited, credited.c.user_id == User.id)
        .order_by(counts.c.qualified.desc(), User.created_at, User.id).limit(10))).all()
    return {"definition": "В таблице referrals хранятся только подтверждённые новые пользователи. Переходы и незавершённые регистрации не учитываются; два счётчика поэтому равны. Награды — бонусные AF, не выплаты Stars.",
        "items": [{"rank": index+1, "user_id": user.id, "avatar_url": user.photo_url,
            "name": " ".join(filter(None, [user.first_name, user.last_name])), "username": validated_username(user.username),
            "invited": count, "qualified": count, "accrued_af": amount(accrued), "credited_bonus_af": amount(credit),
            "profile_url": profile_url(user), "contact_note": None if validated_username(user.username) else "Открытие профиля по ID зависит от настроек Telegram. Если чат недоступен, используйте поддержку в админке."}
            for index, (user, count, accrued, credit) in enumerate(rows)]}


@router.get("")
async def report(start: date | None = None, end: date | None = None, all_time: bool = False,
    timezone: str = Query(default="Europe/Bratislava", max_length=64), limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0),
    owner: User = Depends(require_owner), session: AsyncSession = Depends(get_session)):
    # Authentication committed before this read. One repeatable snapshot for all
    # summary/table queries, and DB-enforced prohibition of accidental writes.
    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
    return await report_data(session, owner.id, start=start, end=end, timezone=timezone, all_time=all_time, limit=limit, offset=offset)


@router.get("/referrals")
async def referrals(owner: User = Depends(require_owner), session: AsyncSession = Depends(get_session)):
    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
    return await referral_leaders(session)
