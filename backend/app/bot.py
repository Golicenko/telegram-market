import httpx
import logging
from fastapi import HTTPException
from urllib.parse import quote, urlencode

from .config import get_settings


logger = logging.getLogger("autoflow.bot")


START_MENU_TEXT = """👋 Добро пожаловать в AutoFlow Market

AutoFlow Market создан для удобной покупки и продажи игровых автомобилей.

Оплата остаётся под защитой до подтверждения получения, а за проектом стоит команда с многолетним опытом работы с сообществом.

Наша аудитория на разных площадках — более 10 000 подписчиков.

Нажмите кнопку ниже, чтобы открыть маркет."""


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
    keyboard = [[{"text": "🚘 Открыть AutoFlow Market", "web_app": {"url": target_url}}]]
    keyboard.append([{"text": "⬅️ Назад" if detailed else "❓ Как это работает", "callback_data": "autoflow:start" if detailed else "autoflow:how"}])
    payload: dict = {
        "chat_id": chat_id,
        "text": HOW_IT_WORKS_TEXT if detailed else START_MENU_TEXT,
        "reply_markup": {"inline_keyboard": keyboard},
    }
    if message_id is not None:
        payload["message_id"] = message_id
    return ("editMessageText" if message_id is not None else "sendMessage"), payload


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


async def answer_bot_callback(callback_query_id: str) -> bool:
    try:
        await call_bot_api("answerCallbackQuery", {"callback_query_id": callback_query_id})
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
    price_xtr: int,
    public_url: str,
) -> dict:
    username = (buyer_username or "").lstrip("@").strip()
    username_line = f"@{username}" if username else "не указан"
    text = (
        "🎓 Новый заказ на персональное обучение\n\n"
        f"Обучение: {title}\n"
        f"Покупатель: {buyer_name}\n"
        f"Username: {username_line}\n"
        f"Telegram ID: {buyer_telegram_id}\n"
        f"Стоимость: {price_xtr} ⭐\n"
        "Оплата: успешно\n"
        "Статус: Ожидает обработки"
    )
    button_rows = []
    if username:
        button_rows.append([{"text": "💬 Написать покупателю", "url": f"https://t.me/{quote(username, safe='')}"}])
    order_url = f"{public_url.rstrip('/')}/?{urlencode({'training_order': purchase_id})}"
    button_rows.append([{"text": "📋 Открыть заказ", "web_app": {"url": order_url}}])
    return {"chat_id": telegram_id, "text": text, "reply_markup": {"inline_keyboard": button_rows}}


async def send_personal_training_order_notification(telegram_id: int, **order) -> bool:
    public_url = get_settings().externally_reachable_url
    if not public_url:
        raise HTTPException(status_code=503, detail="PUBLIC_BASE_URL или RAILWAY_PUBLIC_DOMAIN не настроен")
    await call_bot_api(
        "sendMessage",
        personal_training_order_payload(telegram_id, public_url=public_url, **order),
    )
    return True


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
    content: bytes,
    content_type: str,
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
        async with httpx.AsyncClient(timeout=60) as client:
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
        "file_size": file_info.get("file_size", len(content)),
        "mime_type": file_info.get("mime_type", content_type),
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
            return configured
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("telegram_webhook_configuration_failed error_type=%s", type(exc).__name__)
        return False
