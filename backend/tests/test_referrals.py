"""Real DB persistence and signed-auth/payment tests; SQLite is not a PG lock simulator."""

import hashlib
import hmac
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from sqlalchemy import create_engine, select, func, event
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app import referral_routes, referrals
from app.auth import get_current_user
from app.config import Settings
from app.database import get_session
from app.models import (
    User,
    Wallet,
    WalletTransaction,
    StarPayment,
    StarPaymentIntent,
    Notification,
    Referral,
    ReferralReward,
    ReferralShare,
)
from app.services import process_successful_payment
from test_chat_lifecycle_db import DB


class ReferralDB(DB):
    @asynccontextmanager
    async def begin_nested(self):
        with self.session.begin_nested():
            yield

    async def commit(self):
        self.session.commit()

    async def refresh(self, obj):
        self.session.refresh(obj)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'referrals.db'}")

    # Match transactional savepoints: sqlite's legacy driver otherwise commits
    # a nested registration before the surrounding auth transaction has begun.
    @event.listens_for(engine, "connect")
    def transactional_driver(connection, _):
        connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def explicit_begin(connection):
        connection.exec_driver_sql("BEGIN")

    with engine.begin() as conn:
        for model in (
            User,
            Wallet,
            WalletTransaction,
            StarPayment,
            StarPaymentIntent,
            Notification,
            Referral,
            ReferralReward,
            ReferralShare,
        ):
            conn.execute(CreateTable(model.__table__))
    session = Session(engine, expire_on_commit=False)
    yield ReferralDB(session)
    session.close()
    engine.dispose()


def init_data(telegram_id, code=None):
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Имя <без username>"}),
    }
    if code:
        values["start_param"] = code
    secret = hmac.new(b"WebAppData", b"referral-test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(
        secret,
        "\n".join(f"{key}={value}" for key, value in sorted(values.items())).encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(values)


async def login(db, telegram_id, code=None):
    return await get_current_user(
        Request({"type": "http"}),
        init_data(telegram_id, code),
        None,
        db,
        Settings(bot_token="referral-test-token", debug=False),
    )


def count(db, model):
    return db.session.scalar(select(func.count()).select_from(model))


async def new_payment(db, buyer, amount=100, purpose="topup"):
    intent = StarPaymentIntent(
        id=uuid.uuid4(),
        user_id=buyer.id,
        invoice_payload=f"autoflow_topup:{uuid.uuid4()}",
        xtr_amount=amount,
        status="pending",
        purpose=purpose,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(intent)
    await db.commit()
    return {
        "currency": "XTR",
        "invoice_payload": intent.invoice_payload,
        "telegram_payment_charge_id": str(uuid.uuid4()),
        "total_amount": amount,
    }


@pytest.mark.asyncio
async def test_first_signed_login_only_and_cumulative_milestones_survive_reopen(db):
    referrer = await login(db, 1)
    code = referrer.referral_code
    assert len(code) == 8 and referrals.valid_code(code)
    for index in range(1, 22):
        await login(db, index + 1, code)
        # Repeated launch and refresh must never count twice.
        await login(db, index + 1, code)
        assert count(db, Referral) == min(index, 20)
        wallet = db.session.scalar(select(Wallet).where(Wallet.user_id == referrer.id))
        assert wallet.available_balance == sum(
            Decimal(reward)
            for threshold, reward in referrals.MILESTONES
            if index >= threshold
        )
        await db.commit()
    assert count(db, ReferralReward) == 3
    assert count(db, WalletTransaction) == 3
    await db.commit()
    db.session.close()
    db.session = Session(db.session.bind, expire_on_commit=False)
    owner = await login(db, 1)
    assert owner.referral_code == code
    assert await referrals.referral_count(db, owner.id) == 20
    wallet = db.session.scalar(select(Wallet).where(Wallet.user_id == owner.id))
    assert wallet.available_balance == Decimal("75")


@pytest.mark.asyncio
async def test_existing_self_invalid_and_unsigned_launch_cannot_award(db):
    owner = await login(db, 1)
    existing = await login(db, 2)
    await login(db, 2, owner.referral_code)
    await login(db, 1, owner.referral_code)
    await login(db, 3, "training_" + str(uuid.uuid4()))
    # An unsigned query string is not a referral source.
    await get_current_user(
        Request(
            {
                "type": "http",
                "query_string": urlencode({"startapp": owner.referral_code}).encode(),
            }
        ),
        init_data(4),
        None,
        db,
        Settings(bot_token="referral-test-token"),
    )
    assert count(db, Referral) == 0
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await get_current_user(
            Request({"type": "http"}),
            init_data(5, owner.referral_code) + "tampered",
            None,
            db,
            Settings(bot_token="referral-test-token"),
        )
    assert error.value.status_code == 401
    assert db.session.scalar(select(User.id).where(User.telegram_id == 5)) is None
    assert existing.referral_registration_processed


@pytest.mark.asyncio
async def test_bot_start_waits_for_login_and_first_attribution_stays(db):
    owner = await login(db, 1)
    other = await login(db, 2)
    bot_user = User(
        telegram_id=3,
        first_name="Bot user",
        bot_started=True,
        pending_referral_code=owner.referral_code,
        referral_candidate_at_registration=True,
    )
    db.add(bot_user)
    await db.flush()
    db.add(Wallet(user_id=bot_user.id))
    await db.commit()
    assert count(db, Referral) == 0
    await db.commit()
    await login(db, 3, other.referral_code)
    relation = db.session.get(Referral, bot_user.id)
    assert relation.referrer_id == owner.id
    await db.commit()
    await login(db, 3, other.referral_code)
    assert db.session.get(Referral, bot_user.id).referrer_id == owner.id


@pytest.mark.asyncio
async def test_code_collision_retries_without_replacing_existing_codes(db, monkeypatch):
    owner = await login(db, 1)
    generated = iter([owner.referral_code, "aB123xYZ"])
    monkeypatch.setattr(referrals, "new_code", lambda: next(generated))
    new = await login(db, 2)
    assert new.referral_code == "aB123xYZ"
    assert db.session.get(User, owner.id).referral_code != new.referral_code


@pytest.mark.asyncio
async def test_paid_topup_commission_credited_once_even_after_twenty(db):
    owner = await login(db, 1)
    for n in range(2, 22):
        await login(db, n, owner.referral_code)
    buyer = await login(db, 2)
    payment = await new_payment(db, buyer)
    assert await process_successful_payment(db, buyer.telegram_id, payment)
    assert not await process_successful_payment(db, buyer.telegram_id, payment)
    owner_wallet = db.session.scalar(select(Wallet).where(Wallet.user_id == owner.id))
    buyer_wallet = db.session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
    assert owner_wallet.available_balance == Decimal("80.00")
    assert buyer_wallet.available_balance == Decimal("100.00")
    assert count(db, ReferralReward) == 4
    assert count(db, StarPayment) == 1
    # Rewards themselves are not paid top-ups and do not cascade to other referrers.
    assert count(db, WalletTransaction) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "purpose,amount,bonus",
    [
        ("listing_checkout", 1, ".05"),
        ("training_topup", 3, ".15"),
        ("listing_promotion_topup", 5, ".25"),
        ("training_checkout", 100, "0"),
    ],
)
async def test_exact_shortfalls_and_legacy_direct_purchase(db, purpose, amount, bonus):
    owner = await login(db, 1)
    buyer = await login(db, 2, owner.referral_code)
    payment = await new_payment(db, buyer, amount, purpose)
    assert await process_successful_payment(db, buyer.telegram_id, payment)
    assert db.session.scalar(
        select(Wallet).where(Wallet.user_id == owner.id)
    ).available_balance == Decimal(bonus)


@pytest.mark.asyncio
async def test_failed_credit_rolls_back_payment_and_both_wallets(db, monkeypatch):
    owner = await login(db, 1)
    buyer = await login(db, 2, owner.referral_code)
    payment = await new_payment(db, buyer)
    original = referrals.credit_reward
    buyer_telegram_id = buyer.telegram_id

    async def fail_after_credit(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("simulated crash before commit")

    monkeypatch.setattr(referrals, "credit_reward", fail_after_credit)
    with pytest.raises(RuntimeError):
        await process_successful_payment(db, buyer.telegram_id, payment)
    assert (
        count(db, StarPayment)
        == count(db, ReferralReward)
        == count(db, WalletTransaction)
        == 0
    )
    assert all(
        wallet.available_balance == 0 for wallet in db.session.scalars(select(Wallet))
    )
    await db.commit()
    monkeypatch.setattr(referrals, "credit_reward", original)
    assert await process_successful_payment(db, buyer_telegram_id, payment)


@pytest.mark.asyncio
async def test_wrong_amount_payer_or_currency_never_pays_referrer(db):
    owner = await login(db, 1)
    buyer = await login(db, 2, owner.referral_code)
    payment = await new_payment(db, buyer)
    for telegram_id, override in [
        (1, {}),
        (2, {"total_amount": 999}),
        (2, {"currency": "USD"}),
    ]:
        with pytest.raises(HTTPException):
            await process_successful_payment(db, telegram_id, payment | override)
    assert count(db, ReferralReward) == count(db, StarPayment) == 0


@pytest.mark.asyncio
async def test_native_share_is_current_user_scoped_cached_and_plain_text(
    db, monkeypatch
):
    user = await login(db, 1)
    calls = []

    async def bot(method, payload):
        calls.append((method, payload))
        if method == "getMe":
            return {"result": {"username": "ActualBot", "has_main_web_app": True}}
        return {
            "result": {
                "id": "prepared-for-user-1",
                "expiration_date": int(time.time()) + 3600,
            }
        }

    monkeypatch.setattr(referral_routes, "call_bot_api", bot)
    monkeypatch.setattr(referral_routes, "_identity_cache", None)
    monkeypatch.setattr(referral_routes, "get_settings", lambda: Settings())
    app = FastAPI()
    app.include_router(referral_routes.router)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        summary = await client.get("/api/referrals")
        assert (
            summary.status_code == 200
            and summary.headers["cache-control"] == "no-store"
        )
        body = summary.json()
        assert (
            body["referralCount"] == 0
            and body["referralLimit"] == 20
            and body["commissionPercent"] == 5
        )
        assert (
            body["referralUrl"]
            == f"https://t.me/ActualBot?startapp={user.referral_code}"
        )
        first = await client.post(
            "/api/referrals/share-message",
            json={"user_id": 999, "referralCode": "ATTACK"},
        )
        second = await client.post("/api/referrals/share-message")
        assert (
            first.json()
            == second.json()
            == {"preparedMessageId": "prepared-for-user-1"}
        )
    prepared = [
        payload for method, payload in calls if method == "savePreparedInlineMessage"
    ]
    assert len(prepared) == 1 and prepared[0]["user_id"] == 1
    article = prepared[0]["result"]
    assert article["reply_markup"]["inline_keyboard"] == [
        [{"text": "Перейти в маркет", "url": body["referralUrl"]}]
    ]
    assert "Имя <без username>" in article["input_message_content"]["message_text"]
    assert "parse_mode" not in article["input_message_content"]
    assert "Тебя приглашают" in referrals.invitation_text(None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "has_main,short_name,expected",
    [
        (True, None, "ActualBot?startapp="),
        (False, None, "ActualBot?start="),
        (False, "market", "ActualBot/market?startapp="),
    ],
)
async def test_real_bot_launch_configuration(
    monkeypatch, has_main, short_name, expected
):
    async def bot(*_):
        return {"result": {"username": "ActualBot", "has_main_web_app": has_main}}

    monkeypatch.setattr(referral_routes, "call_bot_api", bot)
    monkeypatch.setattr(referral_routes, "_identity_cache", None)
    monkeypatch.setattr(
        referral_routes,
        "get_settings",
        lambda: Settings(telegram_mini_app_short_name=short_name),
    )
    assert (
        await referral_routes.referral_url("Ab123XYZ")
        == "https://t.me/" + expected + "Ab123XYZ"
    )


@pytest.mark.asyncio
async def test_share_errors_are_readable_and_retries_rate_limited(db, monkeypatch):
    user = await login(db, 1)

    async def url(_):
        return "https://t.me/ActualBot?startapp="

    async def bot(*_):
        raise HTTPException(502, "RAW TELEGRAM ERROR")

    monkeypatch.setattr(referral_routes, "referral_url", url)
    monkeypatch.setattr(referral_routes, "call_bot_api", bot)
    with pytest.raises(HTTPException) as error:
        await referral_routes.prepare_referral_share(Response(), user, db)
    assert error.value.status_code == 502 and "RAW" not in error.value.detail
    with pytest.raises(HTTPException) as retry:
        await referral_routes.prepare_referral_share(Response(), user, db)
    assert retry.value.status_code == 429


@pytest.mark.asyncio
async def test_cap_blocks_share_server_side(db):
    owner = await login(db, 1)
    for n in range(2, 22):
        await login(db, n, owner.referral_code)
    with pytest.raises(HTTPException) as error:
        await referral_routes.prepare_referral_share(Response(), owner, db)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_endpoints_reject_unauthenticated_requests():
    app = FastAPI()
    app.include_router(referral_routes.router)
    # No database is accessed before the missing Telegram signature is rejected.
    app.dependency_overrides[get_session] = lambda: None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/referrals")).status_code == 401
        assert (await client.post("/api/referrals/share-message")).status_code == 401


@pytest.mark.asyncio
async def test_bot_webhook_captures_candidate_but_does_not_reward_until_login(db):
    from app.routes import telegram_webhook

    owner = await login(db, 1)
    settings = Settings(bot_token="referral-test-token")
    tasks = BackgroundTasks()
    update = {
        "message": {
            "from": {"id": 2, "first_name": "Friend"},
            "text": f"/start {owner.referral_code}",
        }
    }
    for _ in range(2):
        assert await telegram_webhook(
            update, tasks, settings.effective_telegram_webhook_secret, db, settings
        ) == {"ok": True}
    assert count(db, Referral) == 0
    await db.commit()
    await login(db, 2)
    assert await referrals.referral_count(db, owner.id) == 1
    assert (
        len(tasks.tasks) == 2
    )  # Menu stays on each explicit /start, no bonus message spam.


@pytest.mark.asyncio
async def test_failed_milestone_rolls_back_registration_and_can_retry(db, monkeypatch):
    owner = await login(db, 1)
    await login(db, 2, owner.referral_code)
    await login(db, 3, owner.referral_code)
    original = referrals.credit_reward
    code = owner.referral_code

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("crash before auth commit")

    monkeypatch.setattr(referrals, "credit_reward", fail)
    with pytest.raises(RuntimeError):
        await login(db, 4, code)
    db.session.rollback()
    assert count(db, Referral) == 2 and count(db, ReferralReward) == 0
    assert db.session.scalar(select(User.id).where(User.telegram_id == 4)) is None
    await db.commit()
    monkeypatch.setattr(referrals, "credit_reward", original)
    await login(db, 4, code)
    assert count(db, Referral) == 3 and count(db, ReferralReward) == 1


@pytest.mark.asyncio
async def test_migrated_existing_bot_only_account_is_never_a_new_referral(db):
    owner = await login(db, 1)
    existing = User(
        telegram_id=2,
        first_name="Before migration",
        bot_started=True,
        referral_registration_processed=True,
        pending_referral_code=owner.referral_code,
    )
    db.add(existing)
    await db.flush()
    db.add(Wallet(user_id=existing.id))
    await db.commit()
    await login(db, 2, owner.referral_code)
    assert count(db, Referral) == 0


@pytest.mark.asyncio
async def test_share_cache_invalidated_when_real_bot_target_changes(db, monkeypatch):
    user = await login(db, 1)
    target = ["https://t.me/FirstBot?start="]
    sent = []

    async def url(code):
        return target[0] + code

    async def bot(_, payload):
        sent.append(payload)
        return {
            "result": {
                "id": f"prepared-{len(sent)}",
                "expiration_date": int(time.time()) + 3600,
            }
        }

    monkeypatch.setattr(referral_routes, "referral_url", url)
    monkeypatch.setattr(referral_routes, "call_bot_api", bot)
    await referral_routes.prepare_referral_share(Response(), user, db)
    cached = db.session.get(ReferralShare, user.id)
    cached.requested_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()
    target[0] = "https://t.me/SecondBot?startapp="
    await referral_routes.prepare_referral_share(Response(), user, db)
    assert len(sent) == 2
    assert (
        sent[1]["result"]["reply_markup"]["inline_keyboard"][0][0]["url"]
        == target[0] + user.referral_code
    )


@pytest.mark.asyncio
async def test_slow_share_response_cannot_overwrite_a_newer_claim(db, monkeypatch):
    user = await login(db, 1)
    user_id = user.id

    async def url(code):
        return "https://t.me/ActualBot?startapp=" + code

    async def bot(*_):
        # A different request finishes while this request awaits Telegram.
        # Sessions use expire_on_commit=False, just like production.
        with Session(db.session.bind, expire_on_commit=False) as other:
            with other.begin():
                latest = other.get(ReferralShare, user_id)
                latest.requested_at += timedelta(seconds=26)
                latest.prepared_message_id = "newer-prepared"
                latest.content_hash = "newer-content-hash"
                latest.expires_at = datetime.now(UTC) + timedelta(hours=1)
        return {
            "result": {
                "id": "older-slow-prepared",
                "expiration_date": int(time.time()) + 3600,
            }
        }

    monkeypatch.setattr(referral_routes, "referral_url", url)
    monkeypatch.setattr(referral_routes, "call_bot_api", bot)
    await referral_routes.prepare_referral_share(Response(), user, db)
    db.session.expire_all()
    cached = db.session.get(ReferralShare, user_id)
    assert cached.prepared_message_id == "newer-prepared"
    assert cached.content_hash == "newer-content-hash"


@pytest.mark.asyncio
async def test_user_locks_allow_ledger_foreign_key_checks(db, monkeypatch):
    from sqlalchemy.dialects.postgresql import dialect
    statements = []
    original_scalar = db.scalar

    async def record(query):
        statements.append(str(query.compile(dialect=dialect())))
        return await original_scalar(query)

    monkeypatch.setattr(db, "scalar", record)
    owner = await login(db, 1)
    for n in range(2, 5):
        await login(db, n, owner.referral_code)
    user_locks = [sql for sql in statements if "FROM users" in sql and " FOR " in sql]
    wallet_locks = [sql for sql in statements if "FROM wallets" in sql and " FOR " in sql]
    assert user_locks and all(sql.endswith("FOR NO KEY UPDATE") for sql in user_locks)
    assert wallet_locks and all(sql.endswith("FOR UPDATE") for sql in wallet_locks)
