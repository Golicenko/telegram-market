import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app import feedback
from app.auth import get_current_user
from app.models import AdminAction, FeedbackCampaign, FeedbackDelivery, FeedbackRequest, SupportTicket, User, UserFeedback, Wallet
from app.schemas import ClientDiagnosticCreate
from test_referral_bonus_postgres import apply_revisions, isolated_pg


def callback(request, action="write", sender=None):
    tid = sender or request.telegram_id
    return {"id": "callback", "data": f"feedback:{action}:{request.id}", "from": {"id": tid}, "message": {"chat": {"type": "private", "id": tid}}}


def message(request, text="Нравится выбор. Но долго грузятся фото.", update_id=7701, reply=True):
    body = {"message_id": 501, "chat": {"id": request.telegram_id, "type": "private"}, "from": {"id": request.telegram_id}, "text": text}
    if reply:
        body["reply_to_message"] = {"message_id": request.prompt_message_id}
    return {"update_id": update_id, "message": body}


async def seed(sessions, count=1):
    async with sessions() as session, session.begin():
        admin = User(telegram_id=900, first_name="Admin", role="admin", bot_started=True)
        users = [User(telegram_id=1000+i, first_name=f"User {i}", role="user", bot_started=True) for i in range(count)]
        session.add_all([admin, *users]);await session.flush()
        session.add_all([Wallet(user_id=u.id, earned_balance=100) for u in users])
    return admin, users


async def campaign(sessions, admin, key=None):
    async with sessions() as session:
        return await feedback.create_campaign(session, admin, key or uuid.uuid4())


async def request(sessions):
    async with sessions() as session:
        return await session.scalar(select(FeedbackRequest).order_by(FeedbackRequest.telegram_id))


def transport(monkeypatch, fail=False):
    calls = []
    async def send(method, payload):
        calls.append((method, payload))
        if fail:
            raise HTTPException(502, "blocked or unknown result")
        return {"ok": True, "result": {"message_id": 100+len(calls)}}
    monkeypatch.setattr(feedback.bot, "call_bot_api", send)
    return calls


def test_buttons_fit_telegram_and_no_automatic_publication_or_copy():
    rid = uuid.uuid4()
    for consent in (True, False):
        assert all(len(row[0]["callback_data"].encode()) <= 64 for row in feedback.buttons(rid, consent)["inline_keyboard"])
    delivery = SimpleNamespace(target_telegram_id=900, kind="forward")
    original = SimpleNamespace(protected=False, telegram_chat_id=1000, telegram_message_id=501)
    method, payload = feedback.delivery_payload(delivery, None, original)
    assert method == "forwardMessage"
    assert payload == {"chat_id": 900, "from_chat_id": 1000, "message_id": 501}
    original.protected = True
    with pytest.raises(ValueError):
        feedback.delivery_payload(delivery, None, original)
    with pytest.raises(ValidationError):
        feedback.CampaignCreate(client_request_id=rid, confirmed=False)


def test_navigation_diagnostics_are_bounded_and_have_no_free_text_fields():
    base = {"error_id": "AF-ABC123", "context": "navigation_market"}
    entry = {"from": "profile", "to": "market", "phase": "visible", "at": 100}
    assert len(ClientDiagnosticCreate(**base, navigation_trace=[entry]).navigation_trace) == 1
    for trace in ([entry]*13, [{**entry, "text": "private"}], [{**entry, "to": "https://private"}]):
        with pytest.raises(ValidationError):
            ClientDiagnosticCreate(**base, navigation_trace=trace)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "support"])
async def test_every_feedback_admin_route_forbids_non_admin(role):
    app = FastAPI();app.include_router(feedback.router)
    async def actor():
        return SimpleNamespace(role=role, id=uuid.uuid4())
    app.dependency_overrides[get_current_user] = actor
    rid = uuid.uuid4()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for method, path, body in [("GET", "", None), ("GET", "/reviews", None), ("POST", "/campaigns", {"client_request_id": str(rid), "confirmed": True}),
            ("POST", f"/campaigns/{rid}/stop", None), ("POST", f"/reviews/{rid}/seen", None)]:
            assert (await client.request(method, "/api/admin/feedback"+path, json=body)).status_code == 403


@pytest.mark.asyncio
async def test_general_messages_commands_and_unrelated_support_replies_never_enter_feedback():
    fake = SimpleNamespace(telegram_id=1000, prompt_message_id=None)
    for update in [message(fake, reply=False), message(fake, "/start"), message(fake, "#рассылка новости"), {"message": {"text": "hello", "chat": {"type": "group"}}}]:
        assert await feedback.handle_message(object(), update) is False


@pytest.mark.asyncio
async def test_concurrent_campaign_and_user_cooldown_stop_are_atomic():
    async with isolated_pg() as (_, sessions):
        admin, users = await seed(sessions, 2)
        key = uuid.uuid4()
        ids = await asyncio.gather(*[campaign(sessions, admin, key) for _ in range(20)])
        assert len(set(ids)) == 1
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(FeedbackRequest)) == 2
            await session.rollback();await feedback.stop_campaign(ids[0], admin, session)
        await campaign(sessions, admin)
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(FeedbackRequest)) == 2, "cancelled requests also enforce cooldown"
            assert await session.scalar(select(func.count()).select_from(AdminAction).where(AdminAction.action == "feedback_campaign_started")) == 2


@pytest.mark.asyncio
async def test_real_feedback_original_consent_and_seen_without_touching_wallet(monkeypatch):
    calls = transport(monkeypatch)
    async with isolated_pg() as (_, sessions):
        admin, users = await seed(sessions);await campaign(sessions, admin)
        assert await feedback._deliver_one(sessions)
        req = await request(sessions)
        assert req.status == "sent"
        async with sessions() as session:
            assert "Ответьте" in await feedback.handle_callback(session, callback(req))
            await feedback.handle_callback(session, callback(req))
        await feedback._deliver_one(sessions);req = await request(sessions)
        assert req.prompt_message_id and len(calls) == 2
        exact = "  Хороший выбор!\nНо фотографии грузятся медленно.  "
        async with sessions() as session:
            assert await feedback.handle_message(session, message(req, exact))
            assert not await feedback.handle_message(session, message(req, exact))
        for _ in range(5):
            await feedback._deliver_one(sessions)
        forwards = [payload for method,payload in calls if method == "forwardMessage"]
        assert forwards == [{"chat_id": admin.telegram_id, "from_chat_id": req.telegram_id, "message_id": 501}]
        async with sessions() as session:
            item = await session.scalar(select(UserFeedback));assert item.text == exact and item.consent == "pending"
            feedback_id=item.id
            await session.rollback()
            assert "Разрешение" in await feedback.handle_callback(session, callback(req, "yes"))
            await feedback.handle_callback(session, callback(req, "yes"))
            await feedback.handle_callback(session, callback(req, "no"))
            result = await feedback.reviews("all", 0, admin, session)
            assert result["items"][0]["consent"] == "private"
            await session.rollback();await feedback.mark_seen(feedback_id, admin, session);await feedback.mark_seen(feedback_id, admin, session)
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(UserFeedback)) == 1
            assert await session.scalar(select(func.count()).select_from(AdminAction).where(AdminAction.action == "feedback_seen")) == 1
            assert (await session.scalar(select(Wallet))).earned_balance == 100
            assert await session.scalar(select(func.count()).select_from(FeedbackDelivery).where(FeedbackDelivery.kind == "prompt")) == 1


@pytest.mark.asyncio
async def test_stop_blocked_bot_and_unknown_restart_never_resend(monkeypatch):
    calls = transport(monkeypatch, fail=True)
    async with isolated_pg() as (_, sessions):
        admin, users = await seed(sessions, 3);cid = await campaign(sessions, admin)
        await feedback._deliver_one(sessions)
        async with sessions() as session, session.begin():
            pending = await session.scalar(select(FeedbackRequest).where(FeedbackRequest.status == "pending").limit(1))
            pending.status, pending.started_at = "sending", datetime.now(UTC)-timedelta(minutes=3)
        await feedback.maintenance(sessions)
        async with sessions() as session:
            await feedback.stop_campaign(cid, admin, session)
        for _ in range(3):
            await feedback._deliver_one(sessions)
        assert len(calls) == 1
        async with sessions() as session:
            statuses = (await session.scalars(select(FeedbackRequest.status))).all()
            assert statuses.count("failed") == 2 and statuses.count("cancelled") == 1


@pytest.mark.asyncio
async def test_busy_users_are_skipped_and_callback_cannot_steal_request(monkeypatch):
    transport(monkeypatch)
    async with isolated_pg() as (_, sessions):
        admin, users = await seed(sessions, 2)
        async with sessions() as session, session.begin():
            session.add(SupportTicket(user_id=users[1].id, author_id=users[1].id, topic="Нужна помощь", status="open"))
        await campaign(sessions, admin);await feedback._deliver_one(sessions);req = await request(sessions)
        async with sessions() as session:
            assert "недоступен" in await feedback.handle_callback(session, callback(req, sender=99999))
            assert await session.scalar(select(func.count()).select_from(FeedbackRequest)) == 1
            await session.rollback();await feedback.handle_callback(session,callback(req,"skip"))
        async with sessions() as session:
            assert (await session.get(FeedbackRequest,req.id)).status=="declined"


@pytest.mark.asyncio
async def test_parallel_workers_forward_protection_and_decline(monkeypatch):
    calls=transport(monkeypatch)
    async with isolated_pg() as (_, sessions):
        admin, users=await seed(sessions);await campaign(sessions,admin)
        await asyncio.gather(*[feedback.deliver_one(sessions) for _ in range(4)])
        assert len(calls)==1
        req=await request(sessions)
        async with sessions() as session:
            await feedback.handle_callback(session,callback(req))
        await feedback._deliver_one(sessions);req=await request(sessions)
        wrong=message(req);wrong["message"]["reply_to_message"]["message_id"]=-1
        async with sessions() as session:
            assert not await feedback.handle_message(session,wrong)
            protected=message(req);protected["message"]["has_protected_content"]=True
            assert await feedback.handle_message(session,protected)
        for _ in range(5):
            await feedback._deliver_one(sessions)
        assert not any(method in {"forwardMessage","copyMessage"} for method,_ in calls)
        async with sessions() as session:
            forward=await session.scalar(select(FeedbackDelivery).where(FeedbackDelivery.kind=="forward"))
            assert forward.status=="failed" and forward.error_type=="protected_content"
            await session.rollback();await feedback.handle_callback(session,callback(req,"no"))
        async with sessions() as session:
            assert (await session.scalar(select(UserFeedback))).consent=="private"


@pytest.mark.asyncio
async def test_feedback_migration_on_existing_schema_preserves_wallets():
    async with isolated_pg(tables=False) as (engine, _):
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: apply_revisions(sync, target="0052_gift_delivery_progress"))
            uid=uuid.uuid4()
            await connection.execute(User.__table__.insert().values(id=uid,telegram_id=991,first_name="Existing",role="user"))
            await connection.execute(Wallet.__table__.insert().values(user_id=uid,earned_balance=11,purchased_balance=10,bonus_balance=12))
            await connection.run_sync(lambda sync: apply_revisions(sync, after="0052_gift_delivery_progress", target="0053_feedback_collection"))
            tables = await connection.scalar(select(func.count()).select_from(FeedbackCampaign))
            assert tables == 0
            assert await connection.scalar(select(Wallet.earned_balance).where(Wallet.user_id==uid)) == 11
