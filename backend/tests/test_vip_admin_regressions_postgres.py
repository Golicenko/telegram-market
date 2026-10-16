"""Real HTTP/row constraints in isolated PostgreSQL; never live Telegram money."""
import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import func, inspect, select

from app.config import Settings, get_settings
from app import services, publications
from app.models import Deal, DealEvent, Listing, ListingPromotion, Notification, PublicationDraft, StarPayment, SupportTicket, User, Wallet, WalletTransaction
from app.services import create_deal_support_case
from test_catalog_and_acceptance_postgres import client_app, headers
from test_publication_stars_postgres import listing_payload, seed_slots, payment
from test_referral_bonus_postgres import isolated_pg, signed_login
from test_seller_orders_postgres import paid_order


@pytest.mark.asyncio
@pytest.mark.parametrize("game", ["car_parking_1", "car_parking_2"])
async def test_initial_vip_with_full_balance_real_constraints(game):
    async with isolated_pg() as (_, sessions):
        seller = await signed_login(sessions, 81001)
        async with sessions() as session, session.begin():
            (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).purchased_balance = 10
        payload = listing_payload().model_copy(update={"promote_for_24h": True, "game_version": game}).model_dump(mode="json")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client_app(sessions)), base_url="http://test") as client:
            first = await client.post("/api/listings", headers=headers(seller), json=payload)
            assert first.status_code == 201, first.text
            for retry in await asyncio.gather(*(client.post("/api/listings", headers=headers(seller), json=payload) for _ in range(3))):
                assert retry.status_code == 201 and retry.json()["id"] == first.json()["id"]
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Listing)) == 1
            assert await session.scalar(select(func.count()).select_from(ListingPromotion)) == 1
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "listing_promotion")) == 1
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).available_balance == 5


async def disputed_order(sessions):
    buyer, seller, listing, deal = await paid_order(sessions)
    admin = await signed_login(sessions, 81002)
    async with sessions() as session, session.begin():
        (await session.get(User, admin.id)).role = "admin"
    async with sessions() as session:
        ticket, *_ = await create_deal_support_case(session, buyer, deal.id, "Автомобиль не получен", "/test.jpg", uuid.uuid4())
    return buyer, seller, listing, deal, admin, ticket


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["support", "control", "resolve"])
@pytest.mark.parametrize("outcome", ["complete", "refund"])
async def test_support_resolution_response_matches_committed_finances(endpoint, outcome):
    async with isolated_pg() as (_, sessions):
        buyer, seller, listing, deal, admin, ticket = await disputed_order(sessions)
        app = client_app(sessions)
        app.dependency_overrides[get_settings] = lambda: Settings(bot_token="referral-test-token", debug=False, admin_id=admin.telegram_id)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
            path = f"/api/admin/support/tickets/{ticket.id}/resolve" if endpoint == "support" else f"/api/admin/deals/{deal.id}/{endpoint}"
            command = {"action" if endpoint == "control" else "outcome": outcome, "reason": "Проверено обеими сторонами", "request_id": str(uuid.uuid4())}
            assert (await client.post(path, headers=headers(buyer), json=command)).status_code == 403
            result = await client.post(path, headers=headers(admin), json=command)
            retry = await client.post(path, headers=headers(admin), json=command)
            assert retry.status_code == 200, retry.text
            assert (await client.post(path, headers=headers(admin), json={**command, "reason": "Другое решение"})).status_code == 409
            assert (await client.post(path, headers=headers(admin), json={**command, "request_id": str(uuid.uuid4())})).status_code == 409
            detail = await client.get(f"/api/admin/deals/{deal.id}/control", headers=headers(admin))
            assert detail.status_code == 200, detail.text
            event = next(e for e in detail.json()["events"] if e["request_id"] == command["request_id"])
            assert event["type"] == f"admin_{outcome}" and event["actor_id"] == str(admin.id)
            assert detail.json()["reserved_af_coins"] == 0
            assert detail.json()["actions"] == ["comment"]
            assert len(detail.json()["transactions"]) >= 2
        async with sessions() as session:
            committed = (await session.get(Deal, deal.id)).status
            payout = (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).earned_balance
            assert result.status_code == 200, f"HTTP {result.status_code}; committed deal={committed}; seller earned={payout}; {result.text}"
            assert committed == ("completed" if outcome == "complete" else "cancelled") and payout == (100 if outcome == "complete" else 0)
            assert result.json()["status"] == ("resolved" if endpoint == "support" else committed)
            assert (await session.get(SupportTicket, ticket.id)).status == "resolved"
            assert (await session.get(Listing, listing.id)).status == ("sold" if outcome == "complete" else "active")
            bw = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            assert bw.frozen_balance == 0 and bw.available_balance == (0 if outcome == "complete" else 100)
            assert await session.scalar(select(func.count()).select_from(DealEvent).where(DealEvent.event_type == f"admin_{outcome}")) == 1
            assert await session.scalar(select(func.count()).select_from(Notification).where(Notification.notification_type == "dispute_resolved")) == 2
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == ("sale_income" if outcome == "complete" else "dispute_refund"))) == 1


@pytest.mark.asyncio
async def test_paid_sixth_publication_full_balance_pin_receipt_and_retry_once():
    async with isolated_pg() as (_, sessions):
        seller = await signed_login(sessions, 81001)
        async with sessions() as session, session.begin():
            await seed_slots(session, seller, 5)
            (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).purchased_balance = 10
        payload = listing_payload().model_copy(update={"promote_for_24h": True})
        async with sessions() as session:
            draft = await publications.create_draft(payload, seller, session)
        receipt = payment(draft)
        async def complete():
            async with sessions() as session:
                draft_id = await publications.receive_payment(session, seller.telegram_id, receipt)
                await publications.fulfill(session, draft_id)
        await asyncio.gather(complete(), complete())
        async with sessions() as session:
            stored = await session.get(PublicationDraft, uuid.UUID(draft["id"]))
            assert stored.status == "published"
            assert (await session.get(Listing, stored.listing_id)).pinned
            assert await session.scalar(select(func.count()).select_from(Listing)) == 6
            assert await session.scalar(select(func.count()).select_from(StarPayment)) == 1
            assert await session.scalar(select(func.count()).select_from(ListingPromotion)) == 1
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).available_balance == 5


@pytest.mark.asyncio
async def test_legacy_separate_pin_real_ledger_foreign_key():
    async with isolated_pg() as (_, sessions):
        seller = await signed_login(sessions, 81001)
        async with sessions() as session, session.begin():
            (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).purchased_balance = 10
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client_app(sessions)), base_url="http://test") as client:
            listing = (await client.post("/api/listings", headers=headers(seller), json=listing_payload().model_dump(mode="json"))).json()
            for _ in range(2):
                result = await client.post(f'/api/listings/{listing["id"]}/promote', headers=headers(seller))
                assert result.status_code == 200, result.text
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(ListingPromotion)) == 1
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).available_balance == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("same_request", [False, True])
async def test_parallel_admin_decisions_one_transition(same_request):
    async with isolated_pg() as (_, sessions):
        _, seller, _, deal, admin, _ = await disputed_order(sessions)
        second = await signed_login(sessions, 81003)
        second.role = admin.role = "admin"
        request_id = uuid.uuid4()
        async def decide(actor, request):
            async with sessions() as session:
                try:
                    await services.resolve_dispute(session, actor, deal.id, "complete", "Обе стороны подтвердили", allow_active=True, request_id=request)
                    return 200
                except services.HTTPException as error:
                    return error.status_code
        results = await asyncio.gather(decide(admin, request_id), decide(admin if same_request else second, request_id if same_request else uuid.uuid4()))
        assert sorted(results) == ([200, 200] if same_request else [200, 409])
        async with sessions() as session:
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).earned_balance == 100
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "sale_income")) == 1


@pytest.mark.asyncio
async def test_failure_before_commit_rolls_back_money_case_and_events(monkeypatch):
    async with isolated_pg() as (_, sessions):
        buyer, seller, listing, deal, admin, ticket = await disputed_order(sessions)
        admin.role = "admin"
        async def fail(*args, **kwargs):
            raise RuntimeError("isolated pre-commit fault")
        monkeypatch.setattr(services, "create_notification", fail)
        async with sessions() as session:
            with pytest.raises(RuntimeError):
                await services.resolve_dispute(session, admin, deal.id, "complete", "Проверенное решение", support_ticket_id=ticket.id, request_id=uuid.uuid4())
        async with sessions() as session:
            assert (await session.get(Deal, deal.id)).status == "disputed"
            assert (await session.get(SupportTicket, ticket.id)).status == "new"
            assert (await session.get(Listing, listing.id)).status == "reserved"
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))).frozen_balance == 100
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).earned_balance == 0
            assert await session.scalar(select(func.count()).select_from(DealEvent).where(DealEvent.event_type == "admin_complete")) == 0


@pytest.mark.asyncio
async def test_support_updated_at_requires_explicit_async_refresh_after_commit():
    from pydantic import ValidationError
    from app.schemas import SupportTicketOut
    async with isolated_pg() as (_, sessions):
        _, _, _, deal, admin, ticket = await disputed_order(sessions)
        admin.role = "admin"
        async with sessions() as session:
            attached = await session.get(SupportTicket, ticket.id)
            await session.commit()
            await services.resolve_dispute(session, admin, deal.id, "complete", "Проверено обеими сторонами", support_ticket_id=ticket.id)
            assert "updated_at" in inspect(attached).expired_attributes
            # This was the old route's response path: finance already committed,
            # but synchronous Pydantic attribute access attempts async DB I/O.
            with pytest.raises(ValidationError, match="MissingGreenlet"):
                SupportTicketOut.model_validate(attached)
            await session.refresh(attached)
            assert SupportTicketOut.model_validate(attached).status == "resolved"


@pytest.mark.asyncio
async def test_control_review_comment_resume_and_inconsistent_reserve_fail_closed():
    async with isolated_pg() as (_, sessions):
        buyer, _, listing, deal, admin, ticket = await disputed_order(sessions)
        application = client_app(sessions)
        application.dependency_overrides[get_settings] = lambda: Settings(bot_token="referral-test-token", debug=False, admin_id=admin.telegram_id)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            url = f"/api/admin/deals/{deal.id}/control"
            command = {"action": "comment", "reason": "Уточнил передачу у сторон", "request_id": str(uuid.uuid4())}
            assert (await client.post(url, headers=headers(admin), json=command)).status_code == 200
            assert (await client.post(url, headers=headers(admin), json=command)).status_code == 200
            assert (await client.post(url, headers=headers(admin), json={**command, "action": "resume", "request_id": str(uuid.uuid4())})).status_code == 409
            # A legacy closed ticket must not allow inconsistent financial data.
            async with sessions() as session, session.begin():
                (await session.get(SupportTicket, ticket.id)).status = "closed"
            assert (await client.post(url, headers=headers(admin), json={**command, "action": "resume", "request_id": str(uuid.uuid4())})).status_code == 200
            assert (await client.post(url, headers=headers(admin), json={**command, "action": "review", "request_id": str(uuid.uuid4())})).json()["status"] == "disputed"
            async with sessions() as session, session.begin():
                (await session.get(Listing, listing.id)).reserved_by_deal_id = None
            result = await client.post(f"/api/admin/deals/{deal.id}/resolve", headers=headers(admin), json={"outcome": "complete", "reason": "Проверка нарушенного резерва", "request_id": str(uuid.uuid4())})
            assert result.status_code == 409
        async with sessions() as session:
            assert (await session.get(Deal, deal.id)).status == "disputed"
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))).frozen_balance == 100
            assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "sale_income")) == 0
