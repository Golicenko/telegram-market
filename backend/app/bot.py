import httpx

from .config import get_settings


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
