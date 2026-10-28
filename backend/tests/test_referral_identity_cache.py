"""Bounded, shared read-only bot verification; no Telegram or database calls."""
import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException

from app import referral_routes


@pytest_asyncio.fixture(autouse=True)
async def isolated_identity_cache(monkeypatch):
    await referral_routes.shutdown_referral_identity()
    monkeypatch.setattr(referral_routes, "_identity_cache", None)
    monkeypatch.setattr(referral_routes, "_identity_expires", 0)
    monkeypatch.setattr(referral_routes, "_identity_task", None)
    monkeypatch.setattr(referral_routes, "_IDENTITY_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(referral_routes, "get_settings", lambda: SimpleNamespace(
        bot_token="isolated-test-token", telegram_mini_app_short_name=None,
    ))
    yield
    await referral_routes.shutdown_referral_identity()


@pytest.mark.asyncio
async def test_twenty_cold_links_share_one_verified_request_and_keep_each_code(monkeypatch):
    calls = []
    started, finish = asyncio.Event(), asyncio.Event()

    async def bot(method, payload):
        calls.append((method, payload))
        started.set()
        await finish.wait()
        return {"result": {"username": "VerifiedBot", "has_main_web_app": True}}

    monkeypatch.setattr(referral_routes, "call_bot_api", bot)
    before = referral_routes.time.monotonic()
    pending = [asyncio.create_task(referral_routes.referral_url(f"Code{i:04d}")) for i in range(20)]
    await asyncio.wait_for(started.wait(), 1)
    assert calls == [("getMe", {})]
    finish.set()
    urls = await asyncio.gather(*pending)
    assert urls == [f"https://t.me/VerifiedBot?startapp=Code{i:04d}" for i in range(20)]
    assert await referral_routes.referral_url("Another1") == "https://t.me/VerifiedBot?startapp=Another1"
    assert len(calls) == 1
    assert before + 300 <= referral_routes._identity_expires <= referral_routes.time.monotonic() + 300
    assert referral_routes._identity_task is None


@pytest.mark.asyncio
async def test_cancelled_caller_does_not_cancel_shared_verification(monkeypatch):
    started, finish = asyncio.Event(), asyncio.Event()
    cancelled = False

    async def bot(*_):
        nonlocal cancelled
        started.set()
        try:
            await finish.wait()
        except asyncio.CancelledError:
            cancelled = True
            raise
        return {"result": {"username": "VerifiedBot", "has_main_web_app": False}}

    monkeypatch.setattr(referral_routes, "call_bot_api", bot)
    first = asyncio.create_task(referral_routes.referral_url("First001"))
    second = asyncio.create_task(referral_routes.referral_url("Second01"))
    await asyncio.wait_for(started.wait(), 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not cancelled and not second.done()
    finish.set()
    assert await second == "https://t.me/VerifiedBot?start=Second01"
    assert not cancelled and referral_routes._identity_task is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "telegram", "invalid"])
async def test_failed_verification_is_not_cached_and_retry_never_uses_expired_target(monkeypatch, failure):
    referral_routes._identity_cache = {"username": "ExpiredBot", "has_main_web_app": False}
    referral_routes._identity_expires = 0
    monkeypatch.setattr(referral_routes, "_IDENTITY_TIMEOUT_SECONDS", .02)
    calls = 0
    cancelled = asyncio.Event()

    async def bot(*_):
        nonlocal calls
        calls += 1
        if calls > 1:
            return {"result": {"username": "CurrentBot", "has_main_web_app": True}}
        if failure == "telegram":
            raise HTTPException(502, "private-provider-details")
        if failure == "invalid":
            return {"result": {"username": "bad/url"}}
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(referral_routes, "call_bot_api", bot)
    outcomes = await asyncio.gather(*(referral_routes.referral_url("Code0001") for _ in range(20)), return_exceptions=True)
    assert calls == 1
    assert all(isinstance(error, HTTPException) and error.status_code == 503 for error in outcomes)
    assert all("private" not in error.detail and "ExpiredBot" not in error.detail for error in outcomes)
    assert referral_routes._identity_task is None
    if failure == "timeout":
        assert cancelled.is_set()
    assert await referral_routes.referral_url("Code0001") == "https://t.me/CurrentBot?startapp=Code0001"
    assert calls == 2


@pytest.mark.asyncio
async def test_empty_token_warmup_does_not_call_telegram(monkeypatch):
    monkeypatch.setattr(referral_routes, "get_settings", lambda: SimpleNamespace(bot_token=""))

    async def forbidden(*_):
        pytest.fail("Empty-token startup must not call Telegram")

    monkeypatch.setattr(referral_routes, "call_bot_api", forbidden)
    await referral_routes.warm_referral_identity()
    assert referral_routes._identity_task is None


@pytest.mark.asyncio
async def test_startup_warmup_does_not_block_and_shutdown_cancels_shared_task(monkeypatch):
    from app import main

    async def unrelated_job():
        return None

    for name in (
        "configure_telegram_webhook", "recover_training_background_jobs", "recover_deal_purchase_notifications",
        "run_deal_transfer_reminder_worker", "run_seller_response_timeout_worker", "run_message_notification_worker",
        "recover_admin_broadcasts", "backfill_referral_codes", "run_analytics_retention", "run_publication_worker", "run_promotion_worker",
    ):
        monkeypatch.setattr(main, name, unrelated_job)
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def bot(*_):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    disposed = []

    async def dispose():
        disposed.append(True)

    monkeypatch.setattr(referral_routes, "call_bot_api", bot)
    monkeypatch.setattr(main, "engine", SimpleNamespace(dispose=dispose))
    context = main.lifespan(FastAPI())
    await asyncio.wait_for(context.__aenter__(), .5)
    try:
        await asyncio.wait_for(started.wait(), 1)
        assert referral_routes._identity_task is not None and not referral_routes._identity_task.done()
    finally:
        await asyncio.wait_for(context.__aexit__(None, None, None), 1)
    assert cancelled.is_set()
    assert referral_routes._identity_task is None
    assert disposed == [True]
