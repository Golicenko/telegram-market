import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from app import routes
from app.bot import deal_support_case_payload
from app.models import (
    AdminAction,
    Deal,
    Listing,
    Notification,
    SupportCaseEvent,
    SupportMessage,
    SupportTicket,
    User,
    Wallet,
    WalletTransaction,
)
from app.services import create_deal_support_case, resolve_dispute


class Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class ScalarCollection:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class Session:
    def __init__(self, deal, listing, buyer, seller, admin):
        self.scalars_queue = [deal, None]
        self.values = {
            (Listing, listing.id): listing,
            (User, buyer.id): buyer,
            (User, seller.id): seller,
        }
        self.admin = admin
        self.added = []

    def begin(self):
        return Transaction()

    async def scalar(self, _query):
        return self.scalars_queue.pop(0)

    async def scalars(self, _query):
        return ScalarCollection([self.admin])

    async def get(self, model, key):
        return self.values.get((model, key))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if hasattr(value, "id") and value.id is None:
                value.id = uuid.uuid4()


def support_fixture():
    buyer = User(id=uuid.uuid4(), telegram_id=10, first_name="Buyer", username=None, role="user")
    seller = User(id=uuid.uuid4(), telegram_id=20, first_name="Seller", username="seller", role="user")
    admin = User(id=uuid.uuid4(), telegram_id=30, first_name="Admin", role="admin", bot_started=True)
    listing = Listing(
        id=uuid.uuid4(), seller_id=seller.id, listing_type="regular", status="reserved",
        brand="Test car", model="", power_hp=1, max_speed_kph=1, description="Description",
        price_af_coins=Decimal("100"), delivery_time_estimate="up_to_1h", views_count=0, pinned=False,
    )
    deal = Deal(
        id=uuid.uuid4(), listing_id=listing.id, buyer_id=buyer.id, seller_id=seller.id,
        status="paid", price_af_coins=Decimal("100"), frozen_amount=Decimal("100"),
        purchased_frozen_amount=Decimal("100"), earned_frozen_amount=Decimal("0"),
        seller_payout=Decimal("70"), platform_commission=Decimal("30"),
    )
    return buyer, seller, admin, listing, deal


@pytest.mark.asyncio
async def test_deal_support_case_links_context_and_freezes_deal_for_admin_review():
    buyer, seller, admin, listing, deal = support_fixture()
    request_id = uuid.uuid4()
    session = Session(deal, listing, buyer, seller, admin)

    ticket, _, _, _, administrators = await create_deal_support_case(
        session, buyer, deal.id, "Продавец не передаёт машину", request_id
    )

    assert ticket.case_type == "deal"
    assert ticket.deal_id == deal.id
    assert ticket.listing_id == listing.id
    assert ticket.buyer_id == buyer.id and ticket.seller_id == seller.id
    assert ticket.author_id == buyer.id
    assert ticket.status == "new"
    assert deal.status == "disputed"
    assert administrators == [admin]
    assert any(isinstance(item, SupportMessage) and item.client_request_id == request_id for item in session.added)
    assert any(isinstance(item, SupportCaseEvent) and item.event_type == "case_created" for item in session.added)
    assert any(isinstance(item, Notification) and item.user_id == admin.id for item in session.added)


def test_support_message_idempotency_is_enforced_by_database():
    constraint = next(item for item in SupportMessage.__table__.constraints if item.name == "uq_support_message_client_request")
    assert [column.name for column in constraint.columns] == ["ticket_id", "sender_id", "client_request_id"]


def test_support_case_has_deal_context_and_audit_table():
    for name in ("deal_id", "listing_id", "buyer_id", "seller_id", "author_id", "resolved_at", "unread_by_admin"):
        assert name in SupportTicket.__table__.columns
    assert SupportCaseEvent.__tablename__ == "support_case_events"
    migration = (Path(__file__).parents[1] / "migrations" / "versions" / "0016_deal_support_cases.py").read_text(encoding="utf-8")
    assert "drop_table(\"support_tickets\")" not in migration
    assert "uq_support_active_deal" in migration
    status_migration = (Path(__file__).parents[1] / "migrations" / "versions" / "0018_support_case_statuses.py").read_text(encoding="utf-8")
    assert "UPDATE support_tickets SET status = 'new'" in status_migration
    assert "drop_table" not in status_migration


def test_admin_support_notification_handles_missing_username_and_opens_case():
    payload = deal_support_case_payload(
        30,
        ticket_id="case-123",
        deal_id="deal-12345678",
        listing_title="Test car",
        buyer_label="Buyer (ID 10)",
        seller_label="@seller",
        author_label="Buyer (ID 10)",
        reason="Продавец не передаёт машину",
        public_url="https://market.example",
    )
    assert "Buyer (ID 10)" in payload["text"]
    assert payload["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"].endswith("support_case=case-123")


class AdminOpenSession:
    def __init__(self, ticket):
        self.ticket = ticket
        self.added = []
        self.committed = False

    async def scalar(self, _query):
        return self.ticket

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.committed = True

    async def refresh(self, _value):
        return None


@pytest.mark.asyncio
async def test_admin_opening_support_case_marks_it_in_progress_and_audits(monkeypatch):
    buyer, _, admin, _, _ = support_fixture()
    ticket = SupportTicket(
        id=uuid.uuid4(), user_id=buyer.id, author_id=buyer.id, case_type="general",
        topic="Помощь", status="open", unread_by_admin=True,
    )
    session = AdminOpenSession(ticket)

    async def output(_session, current):
        return current

    monkeypatch.setattr(routes, "support_ticket_out", output)
    result = await routes.admin_support_ticket(ticket.id, admin, session)

    assert result is ticket
    assert ticket.status == "in_progress" and ticket.unread_by_admin is False
    assert session.committed
    assert any(isinstance(item, SupportCaseEvent) and item.event_type == "admin_opened" for item in session.added)
    assert any(isinstance(item, AdminAction) and item.admin_id == admin.id for item in session.added)


def test_frontend_training_success_and_support_workflows_are_explicit():
    root = Path(__file__).parents[2]
    app = (root / "webapp" / "js" / "app.js").read_text(encoding="utf-8")
    css = (root / "webapp" / "css" / "style.css").read_text(encoding="utf-8")
    assert 'let saved = await api.request(id ? `/admin/training/${id}`' in app
    assert '✅ Обучение успешно изменено' in app
    assert 'materialResult.failures.length' in app
    assert 'training_refresh_after_save' in app
    assert "Возникла проблема" not in app
    assert "🛟 Написать в поддержку" in app
    assert "/deals/${dealId}/support" in app
    assert "--chat-viewport-width" in app
    assert "width:var(--chat-viewport-width,100%)" in css


class ResolutionSession:
    def __init__(self, deal, listing, buyer_wallet, seller_wallet, ticket):
        self.values = [deal, listing, buyer_wallet, seller_wallet, ticket]
        self.added = []

    def begin(self):
        return Transaction()

    async def scalar(self, _query):
        return self.values.pop(0)

    def add(self, value):
        self.added.append(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,expected_deal,expected_listing", [
    ("refund", "cancelled", "active"),
    ("complete", "completed", "sold"),
])
async def test_admin_financial_resolution_is_atomic_with_case_audit(outcome, expected_deal, expected_listing):
    buyer, seller, admin, listing, deal = support_fixture()
    deal.status = "disputed"
    ticket = SupportTicket(
        id=uuid.uuid4(), user_id=buyer.id, author_id=buyer.id, case_type="deal",
        deal_id=deal.id, listing_id=listing.id, buyer_id=buyer.id, seller_id=seller.id,
        topic="Проблема по сделке", status="in_progress", unread_by_admin=False,
    )
    buyer_wallet = Wallet(
        id=uuid.uuid4(), user_id=buyer.id, purchased_balance=Decimal("0"), earned_balance=Decimal("0"),
        purchased_frozen_balance=Decimal("100"), earned_frozen_balance=Decimal("0"),
        total_earned=Decimal("0"), version=0,
    )
    seller_wallet = Wallet(
        id=uuid.uuid4(), user_id=seller.id, purchased_balance=Decimal("0"), earned_balance=Decimal("0"),
        purchased_frozen_balance=Decimal("0"), earned_frozen_balance=Decimal("0"),
        total_earned=Decimal("0"), version=0,
    )
    session = ResolutionSession(deal, listing, buyer_wallet, seller_wallet, ticket)

    result = await resolve_dispute(
        session, admin, deal.id, outcome, "Проверенное решение поддержки", support_ticket_id=ticket.id
    )

    assert result.status == expected_deal
    assert listing.status == expected_listing
    assert ticket.status == "resolved" and ticket.resolved_at is not None
    assert any(isinstance(item, SupportCaseEvent) and item.event_type == f"financial_resolution_{outcome}" for item in session.added)
    assert any(isinstance(item, WalletTransaction) for item in session.added)
    if outcome == "refund":
        assert buyer_wallet.available_balance == Decimal("100.00")
    else:
        assert seller_wallet.earned_balance == Decimal("70.00")
