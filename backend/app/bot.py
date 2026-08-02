import httpx
from fastapi import HTTPException

from .config import get_settings


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
            "provider_token": "",
            "currency": "XTR",
            "prices": [{"label": f"{amount} AF Coins", "amount": amount}],
        },
    )
    return str(data["result"])


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


async def configure_telegram_webhook() -> bool:
    """Register Railway's public HTTPS endpoint without making startup depend on Telegram."""
    settings = get_settings()
    public_url = settings.externally_reachable_url
    if not settings.bot_token or not public_url:
        return False
    payload: dict[str, object] = {
        "url": f"{public_url}/api/telegram/webhook",
        "allowed_updates": ["message", "pre_checkout_query"],
        "drop_pending_updates": False,
    }
    if settings.telegram_webhook_secret:
        payload["secret_token"] = settings.telegram_webhook_secret
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"https://api.telegram.org/bot{settings.bot_token}/setWebhook", json=payload)
            return response.is_success and bool(response.json().get("ok"))
    except (httpx.HTTPError, ValueError):
        return False
