import httpx
import logging
from dataclasses import dataclass
from fastapi import HTTPException
from typing import BinaryIO
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit

from .config import get_settings
from .frontend import versioned_webapp_url


logger = logging.getLogger("autoflow.bot")
_bot_username_cache: str | None = None


@dataclass(frozen=True)
class BroadcastSendResult:
    success: bool
    error_type: str | None = None
    error_message: str | None = None
    retry_after: int | None = None


START_MENU_PHOTO_PATH = "/images/autoflow-start.png"


START_MENU_TEXT = """Добро пожаловать в AutoFlow Market!👋

Покупайте и продавайте машины из Car Parking. 🚙 Также у нас есть профессиональное обучение по Game Guardian — всё объясним, покажем и поможем разобраться.

Аудитория — более 10 000 подписчиков, опыт — 4 года. 🩷

Присоединяйся к нам 👇"""


HOW_IT_WORKS_TEXT = """ℹ️ Как работает AutoFlow Market

AutoFlow Market — единый маркет для CRMP: машины, эксклюзивы и обучение прямо в Telegram.

Здесь не нужно искать продавцов, машины и обучение по разным чатам и каналам — всё собрано в одном месте.

🚗 Как проходит покупка машины

Вы выбираете автомобиль в маркете и нажимаете «Купить».

Если средств хватает, создаётся безопасная сделка.

Если средств не хватает, AutoFlow Market показывает, сколько именно не хватает, и предлагает пополнить ровно недостающую сумму через Telegram Stars.

После подтверждённой оплаты покупка продолжается автоматически.

🛡 Как работает безопасная сделка

Деньги не передаются продавцу сразу.

После оплаты они находятся под защитой AutoFlow Market.

Продавец получает средства только после того, как покупатель подтверждает, что получил всё необходимое.

После подтверждения сделка считается завершённой.

👑 Эксклюзивные автомобили

В отдельном разделе доступны редкие и уникальные машины.

Их можно приобрести напрямую через AutoFlow Market по установленной цене.

🎓 Обучение

В AutoFlow Market доступны два формата обучения.

👑 Персональное обучение

Индивидуальная работа и сопровождение.

После покупки администратор получает уведомление с данными покупателя и связывается с ним для проведения обучения.

⚡ Автовыдача

Готовый цифровой курс.

После подтверждённой оплаты бот автоматически отправляет покупателю приобретённые видео, файлы и другие материалы.

⭐ Оплата

Оплата внутри AutoFlow Market проходит через Telegram Stars.

Всё происходит прямо в Telegram — без переходов на сторонние сайты для самой оплаты.

👥 О проекте

За AutoFlow Market стоит команда с большим опытом работы с сообществом.

Наша совокупная аудитория на разных площадках — более 10 000 подписчиков.

Мы хотим сделать единое место, где покупка, продажа и обучение проходят быстро, удобно и понятно.

AutoFlow Market — всё необходимое в одном Telegram-маркете. 🚘"""


def bot_menu_payload(
    detailed: bool,
    public_url: str,
    *,
    chat_id: int,
    message_id: int | None = None,
    start_payload: str | None = None,
) -> tuple[str, dict]:
    target_url = public_url
    if start_payload:
        separator = "&" if "?" in target_url else "?"
        target_url = f"{target_url}{separator}{urlencode({'start': start_payload})}"
    keyboard = [[{"text": "🚘 Открыть маркетплейс", "web_app": {"url": target_url}}]]
    if detailed:
        keyboard.append([{"text": "⬅️ Назад", "callback_data": "autoflow:start"}])
    if detailed or message_id is not None:
        payload: dict = {
            "chat_id": chat_id,
            "text": HOW_IT_WORKS_TEXT if detailed else START_MENU_TEXT,
            "reply_markup": {"inline_keyboard": keyboard},
        }
        if message_id is not None:
            payload["message_id"] = message_id
        return ("editMessageText" if message_id is not None else "sendMessage"), payload
    parts = urlsplit(public_url)
    photo_url = urlunsplit((parts.scheme, parts.netloc, START_MENU_PHOTO_PATH, parts.query, ""))
    return "sendPhoto", {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": START_MENU_TEXT,
        "reply_markup": {"inline_keyboard": keyboard},
    }


async def send_bot_menu(
    telegram_id: int,
    *,
    detailed: bool = False,
    message_id: int | None = None,
    start_payload: str | None = None,
) -> bool:
    public_url = get_settings().externally_reachable_url
    if not public_url:
        return await send_bot_notification(telegram_id, "AutoFlow Market временно недоступен. Попробуйте открыть приложение позже.")
    public_url = versioned_webapp_url(public_url)
    # A chat-specific menu button can keep an older URL after the default has
    # changed. Refresh it whenever this user starts or reopens the bot menu.
    await configure_chat_menu_button(telegram_id)
    method, payload = bot_menu_payload(
        detailed,
        public_url,
        chat_id=telegram_id,
        message_id=message_id,
        start_payload=start_payload,
    )
    try:
        await call_bot_api(method, payload)
        return True
    except HTTPException:
        return False


def chat_menu_button_payload(public_url: str, chat_id: int | None = None) -> dict:
    payload: dict[str, object] = {
        "menu_button": {
            "type": "web_app",
            "text": "Открыть AutoFlow Market",
            "web_app": {"url": versioned_webapp_url(public_url)},
        }
    }
    if chat_id is not None:
        payload["chat_id"] = chat_id
    return payload


async def configure_chat_menu_button(chat_id: int | None = None) -> bool:
    """Set the current versioned URL for the default or private-chat menu button."""
    settings = get_settings()
    public_url = settings.externally_reachable_url
    if not settings.bot_token or not public_url:
        return False
    try:
        await call_bot_api("setChatMenuButton", chat_menu_button_payload(public_url, chat_id))
        return True
    except HTTPException as exc:
        logger.warning(
            "telegram_menu_button_configuration_failed chat_id=%s status=%s detail=%s",
            chat_id,
            exc.status_code,
            str(exc.detail)[:300],
        )
        return False


async def answer_bot_callback(callback_query_id: str, text: str | None = None, *, show_alert: bool = False) -> bool:
    try:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload.update({"text": text[:200], "show_alert": show_alert})
        await call_bot_api("answerCallbackQuery", payload)
        return True
    except HTTPException:
        return False


async def call_bot_api(method: str, payload: dict) -> dict:
    settings = get_settings()
    if not settings.bot_token:
        raise HTTPException(status_code=503, detail="BOT_TOKEN не настроен")
    url = f"https://api.telegram.org/bot{settings.bot_token}/{method}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload)
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Telegram Bot API временно недоступен") from exc
    if not response.is_success or not data.get("ok"):
        description = data.get("description") or "Telegram Bot API rejected the request"
        raise HTTPException(status_code=502, detail=description)
    return data


async def bot_private_chat_link() -> str:
    """Return the canonical private-chat link for the configured bot."""
    global _bot_username_cache
    if not _bot_username_cache:
        data = await call_bot_api("getMe", {})
        username = str(data.get("result", {}).get("username") or "").strip().lstrip("@")
        if not username or not username.replace("_", "").isalnum():
            raise HTTPException(status_code=502, detail="Telegram не вернул username бота")
        _bot_username_cache = username
    return f"https://t.me/{quote(_bot_username_cache)}"


async def training_mini_app_link(product_id: str) -> str:
    """Build an authenticated Main Mini App deep link for one training product."""

    base_url = await bot_private_chat_link()
    return f"{base_url}?{urlencode({'startapp': f'training_{product_id}'})}"


async def create_star_invoice_link(amount: int, invoice_payload: str) -> str:
    data = await call_bot_api(
        "createInvoiceLink",
        {
            "title": "Пополнение AF Coins",
            "description": f"{amount} AF Coins для использования внутри AUTOFLOW MARKET",
            "payload": invoice_payload,
            "currency": "XTR",
            "prices": [{"label": f"{amount} AF Coins", "amount": amount}],
        },
    )
    return str(data["result"])


async def create_training_invoice_link(amount: int, invoice_payload: str, title: str) -> str:
    data = await call_bot_api(
        "createInvoiceLink",
        {
            "title": title[:32],
            "description": "Оплата обучения в AUTOFLOW MARKET",
            "payload": invoice_payload,
            "currency": "XTR",
            "prices": [{"label": "Обучение", "amount": amount}],
        },
    )
    return str(data["result"])


def personal_training_order_payload(
    telegram_id: int,
    *,
    purchase_id: str,
    title: str,
    buyer_name: str,
    buyer_username: str | None,
    buyer_telegram_id: int,
    price_af_coins: int,
    public_url: str | None,
) -> dict:
    username = (buyer_username or "").lstrip("@").strip()
    username_line = f"@{username}" if username else "не указан"
    text = (
        "🎓 Новое персональное обучение\n\n"
        f"Обучение: {title}\n"
        f"Покупатель: {buyer_name}\n"
        f"Username: {username_line}\n"
        f"Telegram ID: {buyer_telegram_id}\n"
        f"Стоимость: {price_af_coins} AF Coins\n"
        "Статус: Оплачено\n"
        f"Заказ: #{purchase_id[:8]}"
    )
    button_rows = []
    if username:
        button_rows.append([{"text": "💬 Написать покупателю", "url": f"https://t.me/{quote(username, safe='')}"}])
    if public_url:
        order_url = f"{public_url.rstrip('/')}/?{urlencode({'training_order': purchase_id})}"
        button_rows.append([{"text": "📋 Открыть заказ", "web_app": {"url": order_url}}])
    payload = {"chat_id": telegram_id, "text": text}
    if button_rows:
        payload["reply_markup"] = {"inline_keyboard": button_rows}
    return payload


async def send_personal_training_order_notification(telegram_id: int, **order) -> bool:
    public_url = get_settings().externally_reachable_url
    await call_bot_api(
        "sendMessage",
        personal_training_order_payload(telegram_id, public_url=public_url, **order),
    )
    return True


def deal_purchase_notification_payload(
    telegram_id: int,
    *,
    deal_id: str,
    public_url: str,
    buyer_name: str,
    buyer_game_id: str,
    buyer_server: str,
    preferred_delivery_time: str,
    photo_url: str | None = None,
) -> dict:
    target = versioned_webapp_url(
        f"{public_url.rstrip('/')}/?{urlencode({'deal_id': deal_id})}"
    )
    text = (
        "🚗 Вашу машину купили\n\n"
        f"Покупатель: {buyer_name}\n"
        f"Сервер: {buyer_server}\n"
        f"ID: {buyer_game_id}\n"
        f"Удобное время: {preferred_delivery_time} МСК\n\n"
        "Покупатель уже оплатил автомобиль. Свяжитесь с ним и передайте машину по указанным данным."
    )
    payload = {
        "chat_id": telegram_id,
        "reply_markup": {
            "inline_keyboard": [[{
                "text": "💬 Открыть сделку",
                "web_app": {"url": target},
            }]]
        },
    }
    if photo_url:
        payload["photo"] = photo_url if photo_url.startswith(("https://", "http://")) else urljoin(public_url.rstrip("/") + "/", photo_url)
        payload["caption"] = text
    else:
        payload["text"] = text
    return payload


async def send_deal_purchase_notification(telegram_id: int, **deal_details) -> bool:
    public_url = get_settings().externally_reachable_url
    if not public_url:
        return False
    try:
        await call_bot_api(
            "sendPhoto" if deal_details.get("photo_url") else "sendMessage",
            deal_purchase_notification_payload(
                telegram_id,
                public_url=public_url,
                **deal_details,
            ),
        )
        return True
    except HTTPException:
        return False


def deal_transfer_reminder_payload(
    telegram_id: int,
    *,
    deal_id: str,
    public_url: str,
) -> dict:
    base_url = public_url.rstrip("/") + "/"
    confirm_url = versioned_webapp_url(
        f"{base_url}?{urlencode({'deal_id': deal_id, 'buyer_entry': '1'})}"
    )
    support_url = versioned_webapp_url(
        f"{base_url}?{urlencode({'support_deal_id': deal_id})}"
    )
    return {
        "chat_id": telegram_id,
        "text": (
            "🚗 Вам передали автомобиль?\n\n"
            "Продавец сообщил, что автомобиль передан.\n\n"
            "Если вы получили машину — подтвердите получение, чтобы завершить сделку.\n\n"
            "Если возникла проблема — обратитесь в поддержку."
        ),
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "✅ Подтвердить получение", "web_app": {"url": confirm_url}}],
                [{"text": "Поддержка", "web_app": {"url": support_url}}],
            ]
        },
    }


async def send_deal_transfer_reminder(telegram_id: int, *, deal_id: str) -> BroadcastSendResult:
    settings = get_settings()
    public_url = settings.externally_reachable_url
    if not settings.bot_token or not public_url:
        return BroadcastSendResult(False, "configuration", "BOT_TOKEN или публичный URL не настроен")
    payload = deal_transfer_reminder_payload(
        telegram_id,
        deal_id=deal_id,
        public_url=public_url,
    )
    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload)
        data = response.json()
    except httpx.HTTPError:
        return BroadcastSendResult(False, "network", "Telegram Bot API временно недоступен")
    except ValueError:
        return BroadcastSendResult(False, "invalid_response", "Telegram вернул некорректный ответ")
    if not isinstance(data, dict):
        return BroadcastSendResult(False, "invalid_response", "Telegram вернул некорректный ответ")
    if response.is_success and data.get("ok"):
        return BroadcastSendResult(True)
    raw_retry_after = data.get("parameters", {}).get("retry_after") if isinstance(data.get("parameters"), dict) else None
    try:
        retry_after = int(raw_retry_after) if raw_retry_after is not None else None
    except (TypeError, ValueError):
        retry_after = None
    description = str(data.get("description") or "Telegram отклонил отправку")[:500]
    error_type = "rate_limited" if response.status_code == 429 else "recipient_unavailable" if response.status_code in {400, 403} else "telegram_api"
    return BroadcastSendResult(False, error_type, description, retry_after)


def deal_support_case_payload(
    telegram_id: int,
    *,
    ticket_id: str,
    deal_id: str,
    listing_title: str,
    buyer_label: str,
    seller_label: str,
    author_label: str,
    reason: str,
    public_url: str,
) -> dict:
    target = f"{public_url.rstrip('/')}/?{urlencode({'support_case': ticket_id})}"
    text = (
        "🛟 Новое обращение по сделке\n\n"
        f"Сделка: #{deal_id[:8]}\n"
        f"Машина: {listing_title}\n"
        f"Покупатель: {buyer_label}\n"
        f"Продавец: {seller_label}\n"
        f"Автор обращения: {author_label}\n"
        f"Причина: {reason[:1000]}"
    )
    return {
        "chat_id": telegram_id,
        "text": text,
        "reply_markup": {"inline_keyboard": [[{
            "text": "Открыть обращение",
            "web_app": {"url": target},
        }]]},
    }


async def send_deal_support_case_notification(telegram_id: int, **case) -> bool:
    public_url = get_settings().externally_reachable_url
    if not public_url:
        return False
    try:
        await call_bot_api(
            "sendMessage",
            deal_support_case_payload(telegram_id, public_url=public_url, **case),
        )
        return True
    except HTTPException:
        return False


async def answer_pre_checkout_query(query_id: str, ok: bool, error_message: str | None = None) -> bool:
    payload: dict[str, object] = {"pre_checkout_query_id": query_id, "ok": ok}
    if error_message and not ok:
        payload["error_message"] = error_message[:200]
    await call_bot_api("answerPreCheckoutQuery", payload)
    return True


def price_offer_notification_payload(
    telegram_id: int,
    *,
    listing_id: str,
    conversation_id: str,
    offer_id: str,
    amount_af_coins: str,
    public_url: str,
) -> dict:
    chat_url = versioned_webapp_url(
        f"{public_url.rstrip('/')}/?{urlencode({'conversation_id': conversation_id, 'listing_id': listing_id, 'offer_id': offer_id})}"
    )
    return {
        "chat_id": telegram_id,
        "text": (
            "💰 Вам предложили другую цену\n\n"
            "Ваш автомобиль хотят купить за:\n\n"
            f"{amount_af_coins} AF Coins"
        ),
        "reply_markup": {"inline_keyboard": [
            [
                {"text": "✅ Принять", "callback_data": f"offer:accept:{offer_id}"},
                {"text": "❌ Отклонить", "callback_data": f"offer:reject:{offer_id}"},
            ],
            [{"text": "💬 Открыть чат", "web_app": {"url": chat_url}}],
        ]},
    }


async def send_price_offer_notification(telegram_id: int, **offer) -> bool:
    public_url = get_settings().externally_reachable_url
    if not public_url:
        return False
    try:
        await call_bot_api("sendMessage", price_offer_notification_payload(telegram_id, public_url=public_url, **offer))
        return True
    except HTTPException:
        return False


async def send_price_offer_response_notification(
    telegram_id: int,
    *,
    accepted: bool,
    amount_af_coins: str,
    listing_id: str,
    conversation_id: str,
    offer_id: str,
) -> bool:
    public_url = get_settings().externally_reachable_url
    payload: dict = {
        "chat_id": telegram_id,
        "text": (
            f"✅ Продавец согласился на вашу цену — {amount_af_coins} AF"
            if accepted else "Предложение отклонено"
        ),
    }
    if accepted and public_url:
        target = versioned_webapp_url(
            f"{public_url.rstrip('/')}/?{urlencode({'listing_id': listing_id, 'offer_id': offer_id})}"
        )
        payload["reply_markup"] = {"inline_keyboard": [[{
            "text": f"Купить за {amount_af_coins} AF",
            "web_app": {"url": target},
        }]]}
    try:
        await call_bot_api("sendMessage", payload)
        return True
    except HTTPException:
        return False


async def send_bot_notification(telegram_id: int, text: str) -> bool:
    settings = get_settings()
    if not settings.bot_token:
        return False
    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json={"chat_id": telegram_id, "text": text})
            return response.is_success
    except httpx.HTTPError:
        return False

async def send_bot_photo(
    telegram_id: int,
    photo_file_id: str,
    caption: str | None = None,
) -> bool:
    settings = get_settings()

    if not settings.bot_token:
        return False

    url = f"https://api.telegram.org/bot{settings.bot_token}/sendPhoto"

    payload = {
        "chat_id": telegram_id,
        "photo": photo_file_id,
    }

    if caption:
        payload["caption"] = caption[:1024]

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload)

        return response.is_success and bool(response.json().get("ok"))
    except (httpx.HTTPError, ValueError):
        return False


def broadcast_market_payload(
    telegram_id: int,
    *,
    text: str,
    photo: str | None,
    public_url: str,
) -> tuple[str, dict]:
    market_url = versioned_webapp_url(public_url)
    payload: dict = {
        "chat_id": telegram_id,
        "reply_markup": {
            "inline_keyboard": [[{
                "text": "🚘 Открыть Market",
                "web_app": {"url": market_url},
            }]]
        },
    }
    if photo:
        payload["photo"] = photo
        if text:
            payload["caption"] = text[:1024]
        return "sendPhoto", payload
    payload["text"] = text[:4096]
    return "sendMessage", payload


async def send_broadcast_message(
    telegram_id: int,
    *,
    text: str,
    photo: str | None = None,
) -> BroadcastSendResult:
    settings = get_settings()
    public_url = settings.externally_reachable_url
    if not settings.bot_token or not public_url:
        return BroadcastSendResult(False, "configuration", "BOT_TOKEN или публичный URL не настроен")
    if photo and photo.startswith("/"):
        photo = f"{public_url.rstrip('/')}{photo}"
    method, payload = broadcast_market_payload(
        telegram_id, text=text, photo=photo, public_url=public_url
    )
    url = f"https://api.telegram.org/bot{settings.bot_token}/{method}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload)
        data = response.json()
    except httpx.HTTPError:
        return BroadcastSendResult(False, "network", "Telegram Bot API временно недоступен")
    except ValueError:
        return BroadcastSendResult(False, "invalid_response", "Telegram вернул некорректный ответ")
    if not isinstance(data, dict):
        return BroadcastSendResult(False, "invalid_response", "Telegram вернул некорректный ответ")
    if response.is_success and data.get("ok"):
        return BroadcastSendResult(True)
    raw_retry_after = data.get("parameters", {}).get("retry_after") if isinstance(data.get("parameters"), dict) else None
    try:
        retry_after = int(raw_retry_after) if raw_retry_after is not None else None
    except (TypeError, ValueError):
        retry_after = None
    description = str(data.get("description") or "Telegram отклонил отправку")[:500]
    error_type = "rate_limited" if response.status_code == 429 else "recipient_unavailable" if response.status_code in {400, 403} else "telegram_api"
    return BroadcastSendResult(False, error_type, description, retry_after)


async def send_bot_material(telegram_id: int, material_type: str, reference: str, title: str) -> bool:
    if material_type in {"text", "link"}:
        text = reference if material_type == "text" else f"{title}\n{reference}"
        return await send_bot_notification(telegram_id, text)
    methods = {
        "photo": ("sendPhoto", "photo"),
        "video": ("sendVideo", "video"),
        "document": ("sendDocument", "document"),
    }
    method = methods.get(material_type)
    if not method:
        return False
    method_name, payload_key = method
    try:
        await call_bot_api(method_name, {"chat_id": telegram_id, payload_key: reference, "caption": title[:1024]})
        return True
    except HTTPException:
        return False


async def upload_bot_material(
    telegram_id: int,
    material_type: str,
    filename: str,
    content: BinaryIO,
    content_type: str,
    file_size: int,
) -> dict:
    settings = get_settings()
    methods = {
        "photo": ("sendPhoto", "photo"),
        "video": ("sendVideo", "video"),
        "document": ("sendDocument", "document"),
    }
    method = methods.get(material_type)
    if not settings.bot_token or not method:
        raise HTTPException(status_code=400, detail="Неподдерживаемый тип материала")
    method_name, field_name = method
    url = f"https://api.telegram.org/bot{settings.bot_token}/{method_name}"
    try:
        timeout = httpx.Timeout(connect=20, read=120, write=300, pool=20)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                data={"chat_id": str(telegram_id), "caption": "Материал AUTOFLOW MARKET сохранён для автовыдачи"},
                files={field_name: (filename, content, content_type)},
            )
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Не удалось загрузить материал в Telegram") from exc
    if not response.is_success or not payload.get("ok"):
        raise HTTPException(status_code=502, detail=payload.get("description") or "Telegram отклонил материал")
    message = payload["result"]
    file_info = message.get(field_name)
    if field_name == "photo":
        photos = message.get("photo") or []
        file_info = photos[-1] if photos else None
    if not file_info or not file_info.get("file_id"):
        raise HTTPException(status_code=502, detail="Telegram не вернул идентификатор материала")
    return {
        "delivery_reference": file_info["file_id"],
        "file_size": file_info.get("file_size", file_size),
        "mime_type": file_info.get("mime_type", content_type),
        "material_type": material_type,
    }


async def configure_telegram_webhook() -> bool:
    """Register Railway's public HTTPS endpoint without making startup depend on Telegram."""
    settings = get_settings()
    public_url = settings.externally_reachable_url
    if not settings.bot_token or not public_url:
        return False
    payload: dict[str, object] = {
        "url": f"{public_url}/api/telegram/webhook",
        "allowed_updates": ["message", "pre_checkout_query", "callback_query"],
        "drop_pending_updates": False,
    }
    if settings.effective_telegram_webhook_secret:
        payload["secret_token"] = settings.effective_telegram_webhook_secret
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"https://api.telegram.org/bot{settings.bot_token}/setWebhook", json=payload)
            configured = response.is_success and bool(response.json().get("ok"))
            if not configured:
                logger.error("telegram_webhook_configuration_rejected status=%s", response.status_code)
        await configure_chat_menu_button()
        # ADMIN_ID is refreshed explicitly because an old per-chat menu setting
        # overrides Telegram's newly updated default button.
        for admin_telegram_id in sorted(settings.admin_telegram_ids):
            await configure_chat_menu_button(admin_telegram_id)
        return configured
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("telegram_webhook_configuration_failed error_type=%s", type(exc).__name__)
        return False
