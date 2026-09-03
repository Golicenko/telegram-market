import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from app.bot import BroadcastSendResult, deal_purchase_notification_payload, deal_transfer_reminder_payload, inactive_seller_admin_payload
from app.models import AdminAction, Conversation, ConversationMessage, Deal, Listing, User, Wallet, WalletTransaction
from app.schemas import DealDeliveryDetailsCreate
from app.services import auto_cancel_unanswered_deal, save_deal_delivery_details, send_conversation_message, set_deal_status, unpublish_seller_active_listings
from app import routes


class Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class Session:
    def __init__(self, deal, listing, conversation):
        self.deal = deal
        self.values = {
            (Listing, listing.id): listing,
            (Conversation, conversation.id): conversation,
            (Deal, deal.id): deal,
        }
        self.added = []

    def begin(self):
        return Transaction()

    async def scalar(self, _query):
        return self.deal

    async def scalars(self, _query):
        class Rows:
            def __init__(self, values):
                self.values = values

            def all(self):
                return self.values

        return Rows([self.deal.id])

    async def get(self, model, key):
        return self.values.get((model, key))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def fixture():
    buyer = User(id=uuid.uuid4(), telegram_id=101, first_name="Buyer", role="user")
    seller = User(id=uuid.uuid4(), telegram_id=202, first_name="Seller", role="user")
    listing = Listing(
        id=uuid.uuid4(), seller_id=seller.id, listing_type="regular", status="reserved",
        brand="Any", model="Car", power_hp=1, max_speed_kph=1,
        description="Car", price_af_coins=Decimal("100"), views_count=0, pinned=False,
    )
    conversation = Conversation(
        id=uuid.uuid4(), listing_id=listing.id, buyer_id=buyer.id, seller_id=seller.id
    )
    deal = Deal(
        id=uuid.uuid4(), listing_id=listing.id, conversation_id=conversation.id,
        buyer_id=buyer.id, seller_id=seller.id, status="paid",
        price_af_coins=Decimal("100"), frozen_amount=Decimal("100"),
        purchased_frozen_amount=Decimal("100"), earned_frozen_amount=Decimal("0"),
        seller_payout=Decimal("70"), platform_commission=Decimal("30"),
    )
    listing.reserved_by_deal_id = deal.id
    return buyer, seller, listing, conversation, deal


@pytest.mark.asyncio
async def test_delivery_details_are_persisted_on_exact_deal_and_message_is_idempotent():
    buyer, _seller, listing, conversation, deal = fixture()
    session = Session(deal, listing, conversation)

    result = await save_deal_delivery_details(
        session, buyer, deal.id, " 12345678 ", " test server ", "19:00"
    )

    assert result.buyer_game_id == "12345678"
    assert result.buyer_server == "test server"
    assert result.preferred_delivery_time == "Сегодня, 19:00"
    assert result.delivery_timezone == "Europe/Moscow"
    assert result.delivery_details_submitted_at is not None
    assert result.delivery_details_submitted_at.tzinfo is not None
    assert result.seller_response_deadline == result.delivery_details_submitted_at + timedelta(hours=24)
    assert result.seller_purchase_notification_status == "pending"
    messages = [item for item in session.added if isinstance(item, ConversationMessage)]
    assert len(messages) == 1
    assert messages[0].message_type == "system"
    assert "ID покупателя: 12345678" in messages[0].body
    assert "Сервер: test server" in messages[0].body
    assert "Сегодня, 19:00 МСК" in messages[0].body

    retry = Session(deal, listing, conversation)
    await save_deal_delivery_details(retry, buyer, deal.id, "12345678", "test server", "19:00")
    assert not [item for item in retry.added if isinstance(item, ConversationMessage)]


@pytest.mark.asyncio
@pytest.mark.parametrize("game_id", ["AB123456", "XY987654", "ab123456"])
async def test_alphanumeric_game_id_is_preserved_exactly(game_id):
    buyer, _seller, listing, conversation, deal = fixture()
    session = Session(deal, listing, conversation)

    result = await save_deal_delivery_details(
        session, buyer, deal.id, game_id, "test server", "19:00"
    )

    assert result.buyer_game_id == game_id
    message = next(item for item in session.added if isinstance(item, ConversationMessage))
    assert f"ID покупателя: {game_id}" in message.body


def test_game_id_database_column_is_text():
    assert Deal.__table__.c.buyer_game_id.type.python_type is str


@pytest.mark.parametrize("game_id", ["AB123456", "XY987654", "ab123456"])
def test_game_id_request_schema_preserves_letters_and_case(game_id):
    payload = DealDeliveryDetailsCreate(
        buyer_game_id=game_id,
        buyer_server="test server",
        preferred_time="19:00",
    )
    assert payload.buyer_game_id == game_id


@pytest.mark.asyncio
async def test_only_exact_deal_buyer_can_store_delivery_details():
    _buyer, _seller, listing, conversation, deal = fixture()
    outsider = User(id=uuid.uuid4(), telegram_id=303, first_name="Other", role="user")
    with pytest.raises(HTTPException) as error:
        await save_deal_delivery_details(
            Session(deal, listing, conversation), outsider, deal.id, "123", "server", "19:00"
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_seller_cannot_mark_transfer_before_buyer_sends_delivery_details():
    _buyer, seller, listing, conversation, deal = fixture()
    with pytest.raises(HTTPException) as error:
        await set_deal_status(
            Session(deal, listing, conversation), seller, deal.id, "transfer_in_progress"
        )
    assert error.value.status_code == 409
    assert deal.status == "paid"
    assert "игровой ID" in error.value.detail


@pytest.mark.asyncio
async def test_transfer_schedules_one_reminder_in_the_same_status_transition():
    _buyer, seller, listing, conversation, deal = fixture()
    deal.buyer_game_id = "12345678"
    deal.buyer_server = "test server"
    deal.preferred_delivery_time = "Сегодня, 19:00"
    deal.delivery_timezone = "Europe/Moscow"
    deal.delivery_details_submitted_at = datetime.now(UTC)
    deal.seller_response_deadline = deal.delivery_details_submitted_at + timedelta(hours=24)
    before = datetime.now(UTC)

    await set_deal_status(Session(deal, listing, conversation), seller, deal.id, "transfer_in_progress")

    assert deal.status == "transfer_in_progress"
    assert deal.seller_responded_at is not None
    assert deal.buyer_transfer_reminder_status == "pending"
    assert deal.buyer_transfer_reminder_scheduled_at >= before + timedelta(seconds=119)


def test_seller_notification_opens_the_exact_deal():
    deal_id = str(uuid.uuid4())
    payload = deal_purchase_notification_payload(
        202,
        deal_id=deal_id,
        public_url="https://market.example/app",
        buyer_name="Максим",
        buyer_game_id="AB123456",
        buyer_server="test server",
        preferred_delivery_time="Сегодня, 19:00",
        photo_url="/uploads/car.jpg",
    )
    button_url = payload["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"]
    assert parse_qs(urlparse(button_url).query)["deal_id"] == [deal_id]
    assert payload["caption"].count("Вашу машину купили") == 1
    assert payload["caption"].count("AB123456") == 1
    assert "@" not in payload["caption"]
    assert payload["photo"] == "https://market.example/uploads/car.jpg"


def test_buyer_reminder_has_exact_deal_and_support_deep_links():
    deal_id = str(uuid.uuid4())
    payload = deal_transfer_reminder_payload(
        101, deal_id=deal_id, public_url="https://market.example/app"
    )
    buttons = payload["reply_markup"]["inline_keyboard"]
    confirm_query = parse_qs(urlparse(buttons[0][0]["web_app"]["url"]).query)
    support_query = parse_qs(urlparse(buttons[1][0]["web_app"]["url"]).query)
    assert confirm_query["deal_id"] == [deal_id]
    assert confirm_query["buyer_entry"] == ["1"]
    assert support_query["support_deal_id"] == [deal_id]
    assert "Вам передали автомобиль?" in payload["text"]


@pytest.mark.asyncio
async def test_repeated_notification_dispatch_sends_only_once_per_deal(monkeypatch):
    buyer, seller, listing, conversation, deal = fixture()
    seller.bot_started = True
    deal.seller_purchase_notification_status = "pending"
    deal.buyer_game_id = "12345678"
    deal.buyer_server = "test server"
    deal.preferred_delivery_time = "Сегодня, 19:00"
    deal.delivery_timezone = "Europe/Moscow"
    deal.delivery_details_submitted_at = datetime.now(UTC)
    deal.seller_response_deadline = deal.delivery_details_submitted_at + timedelta(seconds=2)

    class NotificationSession(Session):
        async def get(self, model, key):
            if model is User and key == seller.id:
                return seller
            if model is User and key == buyer.id:
                return buyer
            return await super().get(model, key)

    monkeypatch.setattr(routes, "SessionLocal", lambda: NotificationSession(deal, listing, conversation))
    monkeypatch.setattr(routes.get_settings(), "seller_response_timeout_seconds", 2)
    sent = []

    async def fake_send(telegram_id, **details):
        sent.append((telegram_id, details))
        return True

    monkeypatch.setattr(routes, "send_deal_purchase_notification", fake_send)
    await routes.notify_deal_purchase_seller(deal.id)
    await routes.notify_deal_purchase_seller(deal.id)

    assert len(sent) == 1
    assert sent[0][0] == seller.telegram_id
    assert sent[0][1]["deal_id"] == str(deal.id)
    assert sent[0][1]["buyer_game_id"] == "12345678"
    assert sent[0][1]["buyer_server"] == "test server"
    assert deal.seller_purchase_notification_status == "sent"
    assert deal.delivery_details_submitted_at is not None
    assert deal.seller_response_deadline is not None
    assert timedelta(seconds=1) <= deal.seller_response_deadline - deal.seller_purchase_notification_sent_at <= timedelta(seconds=2)


@pytest.mark.asyncio
async def test_failed_seller_telegram_delivery_does_not_remove_financial_deadline(monkeypatch):
    buyer, seller, listing, conversation, deal = fixture()
    seller.bot_started = True
    deal.seller_purchase_notification_status = "pending"
    deal.buyer_game_id = "AB123456"
    deal.buyer_server = "server"
    deal.preferred_delivery_time = "Сегодня, 19:00"
    deal.delivery_timezone = "Europe/Moscow"
    deal.delivery_details_submitted_at = datetime.now(UTC)
    deal.seller_response_deadline = deal.delivery_details_submitted_at + timedelta(hours=24)
    original_deadline = deal.seller_response_deadline

    class NotificationSession(Session):
        async def get(self, model, key):
            if model is User and key == seller.id:
                return seller
            if model is User and key == buyer.id:
                return buyer
            return await super().get(model, key)

    monkeypatch.setattr(routes, "SessionLocal", lambda: NotificationSession(deal, listing, conversation))

    async def failed_send(*_args, **_kwargs):
        return False

    monkeypatch.setattr(routes, "send_deal_purchase_notification", failed_send)
    await routes.notify_deal_purchase_seller(deal.id)

    assert deal.seller_purchase_notification_status == "failed"
    assert deal.seller_purchase_notification_next_attempt_at is not None
    assert deal.seller_response_deadline == original_deadline


@pytest.mark.asyncio
async def test_seller_notification_waits_for_all_delivery_details(monkeypatch):
    _buyer, seller, listing, conversation, deal = fixture()
    seller.bot_started = True
    deal.seller_purchase_notification_status = "pending"
    monkeypatch.setattr(routes, "SessionLocal", lambda: Session(deal, listing, conversation))
    sent = []

    async def fake_send(*args, **kwargs):
        sent.append((args, kwargs))
        return True

    monkeypatch.setattr(routes, "send_deal_purchase_notification", fake_send)
    await routes.notify_deal_purchase_seller(deal.id)

    assert sent == []
    assert deal.seller_purchase_notification_status == "pending"


@pytest.mark.asyncio
async def test_due_transfer_reminder_is_recovered_and_sent_only_once(monkeypatch):
    buyer, _seller, listing, conversation, deal = fixture()
    buyer.bot_started = True
    deal.status = "transfer_in_progress"
    deal.transfer_started_at = datetime.now(UTC) - timedelta(minutes=3)
    deal.buyer_transfer_reminder_status = "pending"
    deal.buyer_transfer_reminder_scheduled_at = datetime.now(UTC) - timedelta(minutes=1)
    deal.buyer_transfer_reminder_attempts = 0

    class ReminderSession(Session):
        async def get(self, model, key):
            if model is User and key == buyer.id:
                return buyer
            return await super().get(model, key)

    monkeypatch.setattr(routes, "SessionLocal", lambda: ReminderSession(deal, listing, conversation))
    sent = []

    async def fake_send(telegram_id, *, deal_id):
        sent.append((telegram_id, deal_id))
        return BroadcastSendResult(True)

    monkeypatch.setattr(routes, "send_deal_transfer_reminder", fake_send)
    await routes.recover_deal_transfer_reminders()
    await routes.recover_deal_transfer_reminders()

    assert sent == [(buyer.telegram_id, str(deal.id))]
    assert deal.buyer_transfer_reminder_status == "sent"
    assert deal.buyer_transfer_reminder_sent_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["completed", "disputed", "cancelled"])
async def test_terminal_or_disputed_deal_skips_pending_transfer_reminder(monkeypatch, terminal_status):
    buyer, _seller, listing, conversation, deal = fixture()
    buyer.bot_started = True
    deal.status = terminal_status
    deal.transfer_started_at = datetime.now(UTC) - timedelta(minutes=3)
    deal.buyer_confirmed_at = datetime.now(UTC)
    deal.completed_at = datetime.now(UTC)
    deal.buyer_transfer_reminder_status = "pending"
    deal.buyer_transfer_reminder_scheduled_at = datetime.now(UTC) - timedelta(minutes=1)

    monkeypatch.setattr(routes, "SessionLocal", lambda: Session(deal, listing, conversation))
    sent = []
    monkeypatch.setattr(routes, "send_deal_transfer_reminder", lambda *args, **kwargs: sent.append(True))

    await routes.notify_deal_transfer_buyer(deal.id)

    assert sent == []
    assert deal.buyer_transfer_reminder_status == "skipped"


@pytest.mark.asyncio
async def test_blocked_buyer_does_not_break_the_deal_or_retry_forever(monkeypatch):
    buyer, _seller, listing, conversation, deal = fixture()
    buyer.bot_started = True
    deal.status = "transfer_in_progress"
    deal.transfer_started_at = datetime.now(UTC) - timedelta(minutes=3)
    deal.buyer_transfer_reminder_status = "pending"
    deal.buyer_transfer_reminder_scheduled_at = datetime.now(UTC) - timedelta(minutes=1)
    deal.buyer_transfer_reminder_attempts = 0

    class ReminderSession(Session):
        async def get(self, model, key):
            if model is User and key == buyer.id:
                return buyer
            return await super().get(model, key)

    monkeypatch.setattr(routes, "SessionLocal", lambda: ReminderSession(deal, listing, conversation))

    async def blocked(*_args, **_kwargs):
        return BroadcastSendResult(False, "recipient_unavailable", "bot was blocked")

    monkeypatch.setattr(routes, "send_deal_transfer_reminder", blocked)
    await routes.notify_deal_transfer_buyer(deal.id)

    assert deal.status == "transfer_in_progress"
    assert deal.buyer_transfer_reminder_status == "failed"
    assert deal.buyer_transfer_reminder_error == "recipient_unavailable"
    assert deal.buyer_transfer_reminder_attempts == 1


@pytest.mark.asyncio
async def test_rate_limit_gets_only_one_bounded_retry(monkeypatch):
    buyer, _seller, listing, conversation, deal = fixture()
    buyer.bot_started = True
    deal.status = "transfer_in_progress"
    deal.transfer_started_at = datetime.now(UTC) - timedelta(minutes=3)
    deal.buyer_transfer_reminder_status = "pending"
    deal.buyer_transfer_reminder_scheduled_at = datetime.now(UTC) - timedelta(minutes=1)
    deal.buyer_transfer_reminder_attempts = 0

    class ReminderSession(Session):
        async def get(self, model, key):
            if model is User and key == buyer.id:
                return buyer
            return await super().get(model, key)

    monkeypatch.setattr(routes, "SessionLocal", lambda: ReminderSession(deal, listing, conversation))
    calls = []

    async def rate_limited(*_args, **_kwargs):
        calls.append(True)
        return BroadcastSendResult(False, "rate_limited", "retry", 2)

    monkeypatch.setattr(routes, "send_deal_transfer_reminder", rate_limited)
    await routes.notify_deal_transfer_buyer(deal.id)
    assert deal.buyer_transfer_reminder_status == "pending"
    assert deal.buyer_transfer_reminder_attempts == 1

    deal.buyer_transfer_reminder_scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
    await routes.notify_deal_transfer_buyer(deal.id)
    assert calls == [True, True]
    assert deal.buyer_transfer_reminder_status == "failed"
    assert deal.buyer_transfer_reminder_attempts == 2


@pytest.mark.asyncio
async def test_buyer_entry_rejects_a_seller_or_unrelated_user():
    _buyer, seller, listing, conversation, deal = fixture()
    with pytest.raises(HTTPException) as error:
        await routes.get_deal_buyer_entry(deal.id, seller, Session(deal, listing, conversation))
    assert error.value.status_code == 404


def test_migration_preserves_old_deals_and_enables_pending_for_new_deals():
    source = (Path(__file__).parents[1] / "migrations" / "versions" / "0020_deal_delivery_flow.py").read_text(encoding="utf-8")
    assert 'server_default="sent"' in source
    assert 'server_default="pending"' in source
    assert "drop_table" not in source

    reminder_migration = (Path(__file__).parents[1] / "migrations" / "versions" / "0024_deal_transfer_reminder.py").read_text(encoding="utf-8")
    assert 'server_default="not_scheduled"' in reminder_migration
    assert "buyer_transfer_reminder_scheduled_at" in reminder_migration
    assert "drop_table" not in reminder_migration

    delivery_migration = (Path(__file__).parents[1] / "migrations" / "versions" / "0029_deal_delivery_server_timezone.py").read_text(encoding="utf-8")
    assert "buyer_server" in delivery_migration
    assert "delivery_timezone" in delivery_migration
    assert "drop_table" not in delivery_migration


def test_seller_purchase_notification_is_only_queued_after_delivery_details():
    source = (Path(__file__).parents[1] / "app" / "routes.py").read_text(encoding="utf-8")
    scheduling = "background_tasks.add_task(notify_deal_purchase_seller, deal.id)"
    assert source.count(scheduling) == 1
    endpoint = source[source.index('router.put("/deals/{deal_id}/delivery-details"'):]
    assert scheduling in endpoint[:2000]


class Rows:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class TimeoutSession:
    def __init__(self, scalar_values, users=None, rows=None):
        self.scalar_values = list(scalar_values)
        self.users = users or {}
        self.rows = list(rows or [])
        self.added = []

    def begin(self):
        return Transaction()

    async def scalar(self, _query):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _query):
        return Rows(self.rows.pop(0) if self.rows else [])

    async def get(self, model, key):
        if model is User:
            return self.users.get(key)
        return None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class StaleNotificationRecoverySession:
    def __init__(self, deal):
        self.deal = deal

    def begin(self):
        return Transaction()

    async def execute(self, statement):
        source = str(statement)
        if "seller_purchase_notification_status" in source:
            self.deal.seller_purchase_notification_status = "pending"
            self.deal.seller_purchase_notification_next_attempt_at = datetime.now(UTC)
        if "seller_timeout_notification_status" in source:
            self.deal.seller_timeout_notification_status = "pending"
            self.deal.seller_timeout_notification_next_attempt_at = datetime.now(UTC)
        return type("Result", (), {"rowcount": 1})()

    async def scalars(self, _query):
        return Rows([])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.mark.asyncio
async def test_stale_sending_notifications_are_recovered_after_restart(monkeypatch):
    _buyer, _seller, _listing, _conversation, deal = fixture()
    stale = datetime.now(UTC) - timedelta(hours=1)
    deal.seller_purchase_notification_status = "sending"
    deal.seller_purchase_notification_claimed_at = stale
    deal.seller_timeout_notification_status = "sending"
    deal.seller_timeout_notification_claimed_at = stale
    session = StaleNotificationRecoverySession(deal)
    monkeypatch.setattr(routes, "SessionLocal", lambda: session)

    await routes.recover_deal_purchase_notifications()
    await routes.recover_seller_response_timeouts()

    assert deal.seller_purchase_notification_status == "pending"
    assert deal.seller_timeout_notification_status == "pending"
    assert deal.seller_purchase_notification_next_attempt_at is not None
    assert deal.seller_timeout_notification_next_attempt_at is not None


@pytest.mark.asyncio
async def test_expired_unanswered_deal_refunds_once_and_never_pays_seller():
    buyer, seller, listing, _conversation, deal = fixture()
    now = datetime.now(UTC)
    deal.delivery_details_submitted_at = now - timedelta(hours=25)
    deal.seller_response_deadline = now - timedelta(hours=1)
    deal.purchased_frozen_amount = Decimal("60")
    deal.earned_frozen_amount = Decimal("40")
    wallet = Wallet(
        user_id=buyer.id,
        purchased_balance=Decimal("0"),
        earned_balance=Decimal("0"),
        purchased_frozen_balance=Decimal("60"),
        earned_frozen_balance=Decimal("40"),
        total_earned=Decimal("0"),
        version=0,
    )
    session = TimeoutSession(
        [deal, listing, wallet],
        users={buyer.id: buyer, seller.id: seller},
        rows=[[]],
    )

    result = await auto_cancel_unanswered_deal(session, deal.id, now=now)

    assert result is not None
    assert deal.status == "cancelled"
    assert deal.seller_timeout_processed_at == now
    assert listing.status == "active"
    assert wallet.available_balance == Decimal("100.00")
    assert wallet.frozen_balance == Decimal("0.00")
    assert wallet.purchased_balance == Decimal("60.00")
    assert wallet.earned_balance == Decimal("40.00")
    refunds = [item for item in session.added if isinstance(item, WalletTransaction)]
    assert len(refunds) == 1
    assert refunds[0].transaction_type == "seller_timeout_refund"
    assert refunds[0].amount == Decimal("100.00")
    assert refunds[0].external_reference == f"seller-timeout-refund:{deal.id}"

    retry = TimeoutSession([deal])
    assert await auto_cancel_unanswered_deal(retry, deal.id, now=now + timedelta(minutes=1)) is None
    assert not [item for item in retry.added if isinstance(item, WalletTransaction)]


@pytest.mark.asyncio
async def test_seller_action_before_deadline_prevents_auto_cancel():
    buyer, seller, listing, conversation, deal = fixture()
    deal.delivery_details_submitted_at = datetime.now(UTC)
    deal.seller_response_deadline = datetime.now(UTC) + timedelta(hours=24)

    await set_deal_status(Session(deal, listing, conversation), seller, deal.id, "seller_contacted")
    assert deal.seller_responded_at is not None

    session = TimeoutSession([deal])
    assert await auto_cancel_unanswered_deal(
        session, deal.id, now=deal.seller_response_deadline + timedelta(seconds=1)
    ) is None


@pytest.mark.asyncio
async def test_seller_chat_message_is_a_response_but_opening_is_not():
    buyer, seller, _listing, conversation, deal = fixture()
    deal.delivery_details_submitted_at = datetime.now(UTC)
    deal.seller_response_deadline = datetime.now(UTC) + timedelta(hours=24)
    conversation.deal_id = deal.id
    session = TimeoutSession(
        [conversation, None, deal],
        users={buyer.id: buyer, seller.id: seller},
    )

    assert deal.seller_responded_at is None
    await send_conversation_message(
        session, seller, conversation.id, "Буду в указанное время", uuid.uuid4(), deal.id
    )
    assert deal.seller_responded_at is not None
    assert len([item for item in session.added if isinstance(item, ConversationMessage)]) == 1


@pytest.mark.asyncio
async def test_generic_pair_chat_does_not_answer_the_legacy_current_deal_pointer():
    buyer, seller, _listing, conversation, deal = fixture()
    deal.delivery_details_submitted_at = datetime.now(UTC)
    deal.seller_response_deadline = datetime.now(UTC) + timedelta(hours=24)
    conversation.deal_id = deal.id
    session = TimeoutSession([conversation, None], users={buyer.id: buyer, seller.id: seller})

    await send_conversation_message(session, seller, conversation.id, "Обычное сообщение", uuid.uuid4())

    assert deal.seller_responded_at is None
    message = next(item for item in session.added if isinstance(item, ConversationMessage))
    assert message.deal_id is None


@pytest.mark.asyncio
async def test_response_in_shared_conversation_marks_only_the_explicit_deal():
    buyer, seller, _listing, conversation, first = fixture()
    second = Deal(
        id=uuid.uuid4(), listing_id=uuid.uuid4(), conversation_id=conversation.id,
        buyer_id=buyer.id, seller_id=seller.id, status="paid",
        price_af_coins=Decimal("50"), frozen_amount=Decimal("50"),
        purchased_frozen_amount=Decimal("50"), earned_frozen_amount=Decimal("0"),
        seller_payout=Decimal("35"), platform_commission=Decimal("15"),
        delivery_details_submitted_at=datetime.now(UTC),
        seller_response_deadline=datetime.now(UTC) + timedelta(hours=24),
    )
    first.delivery_details_submitted_at = datetime.now(UTC)
    first.seller_response_deadline = datetime.now(UTC) + timedelta(hours=24)
    conversation.deal_id = second.id
    session = TimeoutSession([conversation, None, first], users={buyer.id: buyer, seller.id: seller})

    await send_conversation_message(
        session, seller, conversation.id, "Ответ по первой машине", uuid.uuid4(), first.id
    )

    assert first.seller_responded_at is not None
    assert second.seller_responded_at is None
    message = next(item for item in session.added if isinstance(item, ConversationMessage))
    assert message.deal_id == first.id


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["transfer_in_progress", "completed", "cancelled", "disputed"])
async def test_terminal_transfer_and_disputed_deals_are_never_timeout_refunded(status):
    _buyer, _seller, _listing, _conversation, deal = fixture()
    deal.status = status
    deal.delivery_details_submitted_at = datetime.now(UTC) - timedelta(hours=25)
    deal.seller_response_deadline = datetime.now(UTC) - timedelta(hours=1)
    session = TimeoutSession([deal])

    assert await auto_cancel_unanswered_deal(session, deal.id) is None
    assert not [item for item in session.added if isinstance(item, WalletTransaction)]


@pytest.mark.asyncio
async def test_old_timeout_job_cannot_touch_a_new_reservation_after_refund():
    _buyer, _seller, listing, _conversation, old_deal = fixture()
    old_deal.status = "cancelled"
    old_deal.seller_timeout_processed_at = datetime.now(UTC)
    new_deal_id = uuid.uuid4()
    listing.status = "reserved"
    listing.reserved_by_deal_id = new_deal_id

    assert await auto_cancel_unanswered_deal(TimeoutSession([old_deal]), old_deal.id) is None
    assert listing.status == "reserved"
    assert listing.reserved_by_deal_id == new_deal_id


class LockedTransaction:
    def __init__(self, lock):
        self.lock = lock

    async def __aenter__(self):
        await self.lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.lock.release()
        return False


class ConcurrentRefundState:
    def __init__(self, buyer, seller, listing, deal, wallet):
        self.buyer = buyer
        self.seller = seller
        self.listing = listing
        self.deal = deal
        self.wallet = wallet
        self.lock = asyncio.Lock()
        self.added = []


class ConcurrentRefundSession:
    def __init__(self, state):
        self.state = state

    def begin(self):
        return LockedTransaction(self.state.lock)

    async def scalar(self, query):
        entity = query.column_descriptions[0].get("entity")
        return {Deal: self.state.deal, Listing: self.state.listing, Wallet: self.state.wallet}.get(entity)

    async def scalars(self, _query):
        return Rows([])

    async def get(self, model, key):
        if model is User and key == self.state.buyer.id:
            return self.state.buyer
        if model is User and key == self.state.seller.id:
            return self.state.seller
        return None

    def add(self, value):
        self.state.added.append(value)


class SellerRaceSession(ConcurrentRefundSession):
    def __init__(self, state, conversation, entered, proceed):
        super().__init__(state)
        self.conversation = conversation
        self.entered = entered
        self.proceed = proceed
        self.paused = False

    async def scalar(self, query):
        entity = query.column_descriptions[0].get("entity")
        if entity is Conversation:
            if not self.paused:
                self.paused = True
                self.entered.set()
                await self.proceed.wait()
            return self.conversation
        if entity is ConversationMessage:
            return None
        return await super().scalar(query)

    async def get(self, model, key):
        return await super().get(model, key)

    async def flush(self):
        return None


class WorkerRaceSession(ConcurrentRefundSession):
    def __init__(self, state, entered, proceed):
        super().__init__(state)
        self.entered = entered
        self.proceed = proceed
        self.paused = False

    async def scalar(self, query):
        entity = query.column_descriptions[0].get("entity")
        if entity is Deal and not self.paused:
            self.paused = True
            self.entered.set()
            await self.proceed.wait()
        return await super().scalar(query)


@pytest.mark.asyncio
async def test_two_concurrent_workers_release_the_hold_exactly_once():
    buyer, seller, listing, _conversation, deal = fixture()
    now = datetime.now(UTC)
    deal.delivery_details_submitted_at = now - timedelta(hours=25)
    deal.seller_response_deadline = now - timedelta(seconds=1)
    wallet = Wallet(
        user_id=buyer.id, purchased_balance=Decimal("0"), earned_balance=Decimal("0"),
        purchased_frozen_balance=Decimal("100"), earned_frozen_balance=Decimal("0"),
        total_earned=Decimal("0"), version=0,
    )
    state = ConcurrentRefundState(buyer, seller, listing, deal, wallet)

    results = await asyncio.gather(
        auto_cancel_unanswered_deal(ConcurrentRefundSession(state), deal.id, now=now),
        auto_cancel_unanswered_deal(ConcurrentRefundSession(state), deal.id, now=now),
    )

    assert sum(result is not None for result in results) == 1
    refunds = [item for item in state.added if isinstance(item, WalletTransaction)]
    assert len(refunds) == 1
    assert wallet.available_balance == Decimal("100.00")
    assert wallet.frozen_balance == Decimal("0.00")


def response_race_fixture():
    buyer, seller, listing, conversation, deal = fixture()
    deadline = datetime.now(UTC) - timedelta(milliseconds=1)
    deal.delivery_details_submitted_at = deadline - timedelta(hours=24)
    deal.seller_response_deadline = deadline
    conversation.deal_id = deal.id
    wallet = Wallet(
        user_id=buyer.id, purchased_balance=Decimal("0"), earned_balance=Decimal("0"),
        purchased_frozen_balance=Decimal("100"), earned_frozen_balance=Decimal("0"),
        total_earned=Decimal("0"), version=0,
    )
    return buyer, seller, listing, conversation, deal, wallet


@pytest.mark.asyncio
async def test_seller_lock_before_deadline_wins_race_and_prevents_refund():
    buyer, seller, listing, conversation, deal, wallet = response_race_fixture()
    # The seller request reached the server before expiry and holds the same Deal row.
    deal.seller_response_deadline = datetime.now(UTC) + timedelta(seconds=1)
    state = ConcurrentRefundState(buyer, seller, listing, deal, wallet)
    entered, proceed = asyncio.Event(), asyncio.Event()
    seller_task = asyncio.create_task(send_conversation_message(
        SellerRaceSession(state, conversation, entered, proceed),
        seller, conversation.id, "Отвечаю вовремя", uuid.uuid4(), deal.id,
    ))
    await entered.wait()
    worker_task = asyncio.create_task(auto_cancel_unanswered_deal(
        ConcurrentRefundSession(state), deal.id, now=deal.seller_response_deadline + timedelta(seconds=1)
    ))
    proceed.set()
    await seller_task
    assert await worker_task is None
    assert deal.seller_responded_at is not None
    assert wallet.frozen_balance == Decimal("100")


@pytest.mark.asyncio
async def test_worker_lock_after_deadline_wins_race_and_late_seller_gets_409():
    buyer, seller, listing, conversation, deal, wallet = response_race_fixture()
    state = ConcurrentRefundState(buyer, seller, listing, deal, wallet)
    entered, proceed = asyncio.Event(), asyncio.Event()
    worker_task = asyncio.create_task(auto_cancel_unanswered_deal(
        WorkerRaceSession(state, entered, proceed), deal.id, now=datetime.now(UTC)
    ))
    await entered.wait()
    seller_proceed = asyncio.Event()
    seller_proceed.set()
    seller_task = asyncio.create_task(send_conversation_message(
        SellerRaceSession(state, conversation, asyncio.Event(), seller_proceed),
        seller, conversation.id, "Слишком поздно", uuid.uuid4(), deal.id,
    ))
    proceed.set()
    assert await worker_task is not None
    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(seller_task, timeout=1)
    assert error.value.status_code == 409
    assert deal.status == "cancelled"
    assert wallet.available_balance == Decimal("100.00")


@pytest.mark.asyncio
async def test_admin_soft_hides_only_active_seller_listings():
    _buyer, seller, listing, _conversation, _deal = fixture()
    admin = User(id=uuid.uuid4(), telegram_id=999, first_name="Admin", role="admin")
    paused = Listing(
        id=uuid.uuid4(), seller_id=seller.id, listing_type="regular", status="paused",
        brand="Other", model="Car", power_hp=1, max_speed_kph=1,
        description="Car", price_af_coins=Decimal("1"), views_count=0, pinned=False,
    )
    session = TimeoutSession([], users={seller.id: seller}, rows=[[listing]])

    count = await unpublish_seller_active_listings(session, admin, seller.id)

    assert count == 1
    assert listing.status == "paused"
    assert paused.status == "paused"
    actions = [item for item in session.added if isinstance(item, AdminAction)]
    assert len(actions) == 1
    assert actions[0].metadata_json["listing_ids"] == [str(listing.id)]


def test_inactive_seller_admin_buttons_target_exact_user():
    seller_id = str(uuid.uuid4())
    payload = inactive_seller_admin_payload(
        999,
        public_url="https://market.example/app",
        seller_id=seller_id,
        seller_name="Seller",
        seller_telegram_id=202,
        deal_id=str(uuid.uuid4()),
    )
    buttons = payload["reply_markup"]["inline_keyboard"]
    assert parse_qs(urlparse(buttons[0][0]["web_app"]["url"]).query)["admin_user_id"] == [seller_id]
    assert parse_qs(urlparse(buttons[1][0]["web_app"]["url"]).query)["admin_unpublish_seller_id"] == [seller_id]
    assert "Деньги покупателю возвращены" in payload["text"]


@pytest.mark.asyncio
async def test_timeout_telegram_notifications_are_not_duplicated(monkeypatch):
    buyer, seller, _listing, _conversation, deal = fixture()
    admin = User(id=uuid.uuid4(), telegram_id=999, first_name="Admin", role="admin", bot_started=True)
    buyer.bot_started = True
    seller.bot_started = True
    deal.status = "cancelled"
    deal.seller_timeout_processed_at = datetime.now(UTC)
    deal.seller_timeout_notification_status = "pending"

    monkeypatch.setattr(
        routes,
        "SessionLocal",
        lambda: TimeoutSession(
            [deal],
            users={buyer.id: buyer, seller.id: seller},
            rows=[[admin]],
        ),
    )
    direct = []
    admin_notices = []

    async def fake_direct(telegram_id, text):
        direct.append((telegram_id, text))
        return True

    async def fake_admin(telegram_id, **details):
        admin_notices.append((telegram_id, details))
        return True

    monkeypatch.setattr(routes, "send_bot_notification", fake_direct)
    monkeypatch.setattr(routes, "send_inactive_seller_admin_notification", fake_admin)
    monkeypatch.setattr(routes.get_settings(), "admin_id", admin.telegram_id)

    await routes.notify_seller_timeout_cancellation(deal.id)
    await routes.notify_seller_timeout_cancellation(deal.id)

    assert [item[0] for item in direct] == [buyer.telegram_id, seller.telegram_id]
    assert [item[0] for item in admin_notices] == [admin.telegram_id]
    assert deal.seller_timeout_notification_status == "sent"


def test_timeout_migration_is_additive_and_worker_is_database_backed():
    root = Path(__file__).parents[1]
    migration = (root / "migrations" / "versions" / "0030_seller_response_timeout.py").read_text(encoding="utf-8")
    routes_source = (root / "app" / "routes.py").read_text(encoding="utf-8")
    assert "seller_response_deadline" in migration
    assert "conversation_messages" in migration
    assert "drop_table" not in migration
    assert "Existing deals deliberately keep NULL deadlines" in migration
    assert "UPDATE deals" not in migration
    assert "Deal.seller_response_deadline <= now" in routes_source
    assert "sleep(86400)" not in routes_source
    assert ".limit(100)" in routes_source
    assert "while True:" in routes_source
    assert "seller_timeout_notification_claimed_at < stale_cutoff" in routes_source
    assert "seller_purchase_notification_claimed_at < stale_cutoff" in routes_source


def test_timeout_refund_has_database_and_state_idempotency_guards():
    external_reference = WalletTransaction.__table__.c.external_reference
    assert external_reference.unique is True
    source = (Path(__file__).parents[1] / "app" / "services.py").read_text(encoding="utf-8")
    timeout_service = source[source.index("async def auto_cancel_unanswered_deal"):source.index("async def unpublish_seller_active_listings")]
    assert ".with_for_update()" in timeout_service
    assert "seller_timeout_processed_at is not None" in timeout_service
    assert 'external_reference=f"seller-timeout-refund:{deal.id}"' in timeout_service
