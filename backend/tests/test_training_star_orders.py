import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException

from app import bot as bot_module, routes
from app.bot import personal_training_order_payload, send_bot_material, send_personal_training_order_notification
from app.config import Settings
from app.models import Conversation, StarPayment, StarPaymentIntent, TrainingProduct, TrainingPurchase, User, Wallet
from app.services import process_successful_payment, purchase_training_product, update_training_purchase_status


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSession:
    def __init__(self, scalar_values=()):
        self.scalar_values = list(scalar_values)
        self.added = []

    def begin(self):
        return FakeTransaction()

    async def scalar(self, _query):
        return self.scalar_values.pop(0) if self.scalar_values else None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if hasattr(value, "id") and value.id is None:
                value.id = uuid.uuid4()


def make_wallet(user_id, purchased="0"):
    return Wallet(
        user_id=user_id,
        purchased_balance=Decimal(purchased),
        earned_balance=Decimal("0"),
        purchased_frozen_balance=Decimal("0"),
        earned_frozen_balance=Decimal("0"),
        total_earned=Decimal("0"),
        version=0,
    )


def make_personal_product(admin_id, price="100"):
    return TrainingProduct(
        id=uuid.uuid4(),
        admin_id=admin_id,
        title="Персональное обучение",
        short_description="Краткое описание обучения",
        full_description="Полное описание персонального обучения",
        cover_url="/uploads/personal.jpg",
        product_type="personal",
        price_af_coins=Decimal(price),
        availability="available",
        published=True,
        pinned=False,
    )


def test_admin_notification_links_to_real_username_and_persisted_order():
    payload = personal_training_order_payload(
        10,
        purchase_id="order-123",
        title="Персональное обучение",
        buyer_name="Иван Иванов",
        buyer_username="buyer_name",
        buyer_telegram_id=123456,
        price_af_coins=100,
        public_url="https://autoflow.example",
    )

    button_rows = payload["reply_markup"]["inline_keyboard"]
    assert payload["chat_id"] == 10
    assert "Telegram ID: 123456" in payload["text"]
    assert "Username: @buyer_name" in payload["text"]
    assert "Стоимость: 100 AF Coins" in payload["text"]
    assert "Статус: Оплачено" in payload["text"]
    assert "Заказ: #order-12" in payload["text"]
    assert button_rows[0][0]["url"] == "https://t.me/buyer_name"
    assert button_rows[1][0]["web_app"]["url"] == "https://autoflow.example/?training_order=order-123"


def test_training_jobs_are_recovered_after_process_restart():
    root = Path(__file__).parents[1]
    routes_source = (root / "app" / "routes.py").read_text(encoding="utf-8")
    main_source = (root / "app" / "main.py").read_text(encoding="utf-8")
    migration = (root / "migrations" / "versions" / "0017_training_order_delivery.py").read_text(encoding="utf-8")
    assert "recover_training_background_jobs" in routes_source
    assert 'asyncio.create_task(run_startup_job("training_recovery", recover_training_background_jobs))' in main_source
    assert "await asyncio.gather(*recovery_tasks, return_exceptions=True)" in main_source
    assert "Статус доставки уведомления до обновления неизвестен" in migration
    assert "title_snapshot" in migration


def test_admin_notification_omits_broken_chat_link_without_username():
    payload = personal_training_order_payload(
        10,
        purchase_id="order-456",
        title="Персональное обучение",
        buyer_name="Покупатель",
        buyer_username=None,
        buyer_telegram_id=654321,
        price_af_coins=150,
        public_url="https://autoflow.example/",
    )

    button_rows = payload["reply_markup"]["inline_keyboard"]
    assert "Username: не указан" in payload["text"]
    assert len(button_rows) == 1
    assert "url" not in button_rows[0][0]
    assert button_rows[0][0]["web_app"]["url"].endswith("training_order=order-456")


@pytest.mark.asyncio
async def test_personal_training_admin_notification_is_really_sent(monkeypatch):
    calls = []

    async def fake_call(method, payload):
        calls.append((method, payload))
        return {"ok": True}

    settings = type("Settings", (), {"externally_reachable_url": "https://autoflow.example"})()
    monkeypatch.setattr(bot_module, "get_settings", lambda: settings)
    monkeypatch.setattr(bot_module, "call_bot_api", fake_call)

    sent = await send_personal_training_order_notification(
        10,
        purchase_id="order-789",
        title="Персональное обучение",
        buyer_name="Иван",
        buyer_username="buyer",
        buyer_telegram_id=20,
        price_af_coins=100,
    )

    assert sent is True
    assert calls[0][0] == "sendMessage"
    assert "Новое персональное обучение" in calls[0][1]["text"]


@pytest.mark.asyncio
async def test_personal_training_notification_still_sends_without_public_url(monkeypatch):
    calls = []

    async def fake_call(method, payload):
        calls.append((method, payload))
        return {"ok": True}

    settings = type("Settings", (), {"externally_reachable_url": None})()
    monkeypatch.setattr(bot_module, "get_settings", lambda: settings)
    monkeypatch.setattr(bot_module, "call_bot_api", fake_call)
    assert await send_personal_training_order_notification(
        10,
        purchase_id="order-no-url",
        title="Персональное обучение",
        buyer_name="Иван",
        buyer_username=None,
        buyer_telegram_id=20,
        price_af_coins=100,
    ) is True
    assert calls[0][1]["chat_id"] == 10
    assert "reply_markup" not in calls[0][1]


def test_personal_order_notification_uses_configured_admin_id(monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(admin_id=777))
    stale_seller = User(id=uuid.uuid4(), telegram_id=10, first_name="Старый админ", role="admin", bot_started=False)
    assert routes.resolve_training_admin_telegram_id(stale_seller) == 777


@pytest.mark.asyncio
async def test_successful_payment_queues_admin_notification_after_order_creation(monkeypatch):
    buyer = User(id=uuid.uuid4(), telegram_id=20, first_name="Иван", username="buyer", role="user")
    intent = StarPaymentIntent(
        id=uuid.uuid4(), user_id=buyer.id, invoice_payload="autoflow_training:test", xtr_amount=100,
        purpose="training_checkout", status="paid", checkout_status="pending", training_product_id=uuid.uuid4(),
    )
    purchase = TrainingPurchase(
        id=uuid.uuid4(), product_id=intent.training_product_id, buyer_id=buyer.id, seller_id=uuid.uuid4(),
        buyer_telegram_id=buyer.telegram_id, buyer_display_name="Иван", buyer_username="buyer",
        product_type="personal", title_snapshot="Курс", cover_url_snapshot="/cover.jpg",
        price_af_coins=Decimal("100"), seller_payout=Decimal("70"), platform_commission=Decimal("30"),
        status="awaiting_start", delivery_status="not_applicable", payment_status="paid",
        admin_notification_status="pending", purchased_frozen_amount=Decimal("100"), earned_frozen_amount=Decimal("0"),
    )

    class WebhookSession:
        def __init__(self): self.values = [intent, buyer]
        async def scalar(self, _query): return self.values.pop(0)
        async def commit(self): return None

    async def paid(*_args, **_kwargs): return True
    async def complete(*_args, **_kwargs): return intent, purchase, True
    monkeypatch.setattr(routes, "process_successful_payment", paid)
    monkeypatch.setattr(routes, "complete_training_payment_intent", complete)
    tasks = BackgroundTasks()
    settings = Settings(bot_token="test-token", admin_id=777)
    update = {"message": {"from": {"id": 20}, "successful_payment": {
        "currency": "XTR", "invoice_payload": intent.invoice_payload,
        "telegram_payment_charge_id": "charge-1", "total_amount": 100,
    }}}

    assert await routes.telegram_webhook(update, tasks, settings.effective_telegram_webhook_secret, WebhookSession(), settings) == {"ok": True}
    assert any(task.func is routes.notify_personal_training_admin and task.args == (purchase.id,) for task in tasks.tasks)


@pytest.mark.asyncio
async def test_admin_orders_endpoint_returns_paid_personal_order(monkeypatch):
    admin = User(id=uuid.uuid4(), telegram_id=777, first_name="Admin", role="admin")
    buyer = User(id=uuid.uuid4(), telegram_id=20, first_name="Иван", username="buyer", role="user")
    purchase = TrainingPurchase(
        id=uuid.uuid4(), product_id=uuid.uuid4(), buyer_id=buyer.id, seller_id=admin.id,
        buyer_telegram_id=buyer.telegram_id, buyer_display_name="Иван", buyer_username="buyer",
        product_type="personal", title_snapshot="Курс", cover_url_snapshot="/cover.jpg",
        price_af_coins=Decimal("100"), seller_payout=Decimal("70"), platform_commission=Decimal("30"),
        status="awaiting_start", delivery_status="not_applicable", payment_status="paid",
        admin_notification_status="pending", purchased_frozen_amount=Decimal("100"), earned_frozen_amount=Decimal("0"),
    )

    class Rows:
        def __init__(self, values): self.values = values
        def all(self): return self.values

    class AdminOrderSession:
        def __init__(self): self.results = [[purchase], [buyer]]
        async def scalars(self, _query): return Rows(self.results.pop(0))

    async def output(_session, current, _buyer=None): return current
    monkeypatch.setattr(routes, "training_purchase_admin_out", output)
    orders = await routes.all_training_orders("personal", None, admin, AdminOrderSession())
    assert orders == [purchase]
    assert orders[0].payment_status == "paid"


@pytest.mark.asyncio
async def test_personal_purchase_persists_telegram_snapshot_and_never_creates_internal_chat():
    admin = User(id=uuid.uuid4(), telegram_id=10, first_name="Администратор", role="admin")
    buyer = User(
        id=uuid.uuid4(), telegram_id=20, first_name="Иван", last_name="Иванов",
        username="buyer_name", role="user",
    )
    product = make_personal_product(admin.id)
    buyer_wallet = make_wallet(buyer.id, "100")
    session = FakeSession([product, None, buyer_wallet])

    purchase, created = await purchase_training_product(
        session,
        buyer,
        product.id,
        telegram_payment_charge_id="training-charge-1",
        expected_price=Decimal("100"),
    )

    assert created is True
    assert purchase.status == "awaiting_start"
    assert purchase.buyer_telegram_id == buyer.telegram_id
    assert purchase.buyer_display_name == "Иван Иванов"
    assert purchase.buyer_username == "buyer_name"
    assert purchase.telegram_payment_charge_id == "training-charge-1"
    assert purchase.payment_status == "paid"
    assert purchase.admin_notification_status == "pending"
    assert buyer_wallet.available_balance == Decimal("0.00")
    assert buyer_wallet.frozen_balance == Decimal("100.00")
    assert not any(isinstance(item, Conversation) for item in session.added)


@pytest.mark.asyncio
async def test_af_coin_purchase_endpoint_creates_personal_order_and_notifies_admin(monkeypatch):
    buyer = User(id=uuid.uuid4(), telegram_id=20, first_name="Иван", role="user")
    purchase = TrainingPurchase(
        id=uuid.uuid4(), product_id=uuid.uuid4(), buyer_id=buyer.id, seller_id=uuid.uuid4(),
        buyer_telegram_id=buyer.telegram_id, buyer_display_name="Иван", product_type="personal",
        title_snapshot="Курс", cover_url_snapshot="/cover.jpg", price_af_coins=Decimal("100"),
        seller_payout=Decimal("70"), platform_commission=Decimal("30"), status="awaiting_start",
        delivery_status="not_applicable", payment_status="paid", admin_notification_status="pending",
        purchased_frozen_amount=Decimal("100"), earned_frozen_amount=Decimal("0"),
    )

    async def buy(*_args, **_kwargs): return purchase, True
    async def output(_session, current): return current
    monkeypatch.setattr(routes, "purchase_training_product", buy)
    monkeypatch.setattr(routes, "training_purchase_out", output)
    tasks = BackgroundTasks()

    result = await routes.purchase_training_with_af_coins(purchase.product_id, tasks, buyer, object())

    assert result is purchase
    assert any(task.func is routes.notify_personal_training_admin and task.args == (purchase.id,) for task in tasks.tasks)


@pytest.mark.asyncio
async def test_af_coin_purchase_endpoint_starts_automatic_delivery_once(monkeypatch):
    buyer = User(id=uuid.uuid4(), telegram_id=20, first_name="Иван", role="user")
    purchase = TrainingPurchase(
        id=uuid.uuid4(), product_id=uuid.uuid4(), buyer_id=buyer.id, seller_id=uuid.uuid4(),
        buyer_telegram_id=buyer.telegram_id, buyer_display_name="Иван", product_type="automatic",
        title_snapshot="Автокурс", cover_url_snapshot="/cover.jpg", price_af_coins=Decimal("100"),
        seller_payout=Decimal("70"), platform_commission=Decimal("30"), status="completed",
        delivery_status="pending", payment_status="paid", admin_notification_status="not_required",
        purchased_frozen_amount=Decimal("0"), earned_frozen_amount=Decimal("0"),
    )
    delivery_calls = []

    async def buy(*_args, **_kwargs): return purchase, True
    async def begin(_session, buyer_id, purchase_id, cooldown_seconds):
        delivery_calls.append((buyer_id, purchase_id, cooldown_seconds)); purchase.delivery_status = "sending"; return purchase
    async def output(_session, current): return current
    monkeypatch.setattr(routes, "purchase_training_product", buy)
    monkeypatch.setattr(routes, "begin_training_delivery", begin)
    monkeypatch.setattr(routes, "training_purchase_out", output)
    tasks = BackgroundTasks()

    result = await routes.purchase_training_with_af_coins(purchase.product_id, tasks, buyer, object())

    assert result.delivery_status == "sending"
    assert delivery_calls == [(buyer.id, purchase.id, 0)]
    assert any(task.func is routes.deliver_training_materials and task.args == (purchase.id,) for task in tasks.tasks)


@pytest.mark.asyncio
async def test_training_successful_payment_is_credited_once_by_charge_id():
    buyer = User(id=uuid.uuid4(), telegram_id=77, first_name="Покупатель", role="user")
    wallet = make_wallet(buyer.id)
    intent = StarPaymentIntent(
        id=uuid.uuid4(),
        user_id=buyer.id,
        invoice_payload="autoflow_training:payment-1",
        xtr_amount=100,
        purpose="training_checkout",
        context={},
        training_product_id=uuid.uuid4(),
        checkout_status="pending",
        status="pending",
    )
    payment = {
        "currency": "XTR",
        "invoice_payload": intent.invoice_payload,
        "telegram_payment_charge_id": "training-charge-unique",
        "total_amount": 100,
    }
    session = FakeSession([None, intent, buyer, wallet])

    assert await process_successful_payment(session, buyer.telegram_id, payment) is True
    assert wallet.available_balance == Decimal("100.00")
    assert intent.status == "paid"
    assert len([item for item in session.added if isinstance(item, StarPayment)]) == 1

    duplicate = FakeSession([uuid.uuid4()])
    assert await process_successful_payment(duplicate, buyer.telegram_id, payment) is False
    assert wallet.available_balance == Decimal("100.00")


@pytest.mark.asyncio
async def test_regular_user_cannot_change_personal_training_status():
    regular_user = User(id=uuid.uuid4(), telegram_id=30, first_name="User", role="user")

    with pytest.raises(HTTPException) as error:
        await update_training_purchase_status(FakeSession(), regular_user, uuid.uuid4(), "completed")

    assert error.value.status_code == 403


def test_training_payment_charge_id_is_unique_in_database_model():
    constraints = {getattr(item, "name", None) for item in TrainingPurchase.__table__.constraints}
    assert any(
        getattr(column, "name", None) == "telegram_payment_charge_id" and column.unique
        for column in TrainingPurchase.__table__.columns
    )
    assert "uq_training_purchase_product_buyer" in constraints


@pytest.mark.asyncio
async def test_automatic_delivery_uses_telegram_file_ids_for_video_and_document(monkeypatch):
    calls = []

    async def fake_call(method, payload):
        calls.append((method, payload))
        return {"ok": True, "result": {}}

    monkeypatch.setattr(bot_module, "call_bot_api", fake_call)

    assert await send_bot_material(77, "video", "telegram-video-file-id", "Видео") is True
    assert await send_bot_material(77, "document", "telegram-document-file-id", "Документ") is True
    assert calls == [
        ("sendVideo", {"chat_id": 77, "video": "telegram-video-file-id", "caption": "Видео"}),
        ("sendDocument", {"chat_id": 77, "document": "telegram-document-file-id", "caption": "Документ"}),
    ]
