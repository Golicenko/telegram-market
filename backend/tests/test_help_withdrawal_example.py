"""Help projections use the real gift calculator without creating a quote or reserve."""
import asyncio
import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from sqlalchemy import func, select

from app import gift_withdrawals, routes
from app.auth import get_current_user
from app.database import get_session
from app.models import GiftWithdrawalQuote, Wallet, WithdrawalRequest
from test_manual_gift_withdrawals import db as gift_db  # noqa: F401


@pytest_asyncio.fixture(autouse=True)
async def isolated_help_catalog(monkeypatch):
    await routes.shutdown_help_gift_catalog()
    monkeypatch.setattr(routes, "_help_gift_catalog_cache", None)
    monkeypatch.setattr(routes, "_help_gift_catalog_expires", 0)
    monkeypatch.setattr(routes, "_help_gift_catalog_task", None)
    monkeypatch.setattr(routes, "_HELP_GIFT_CATALOG_TIMEOUT_SECONDS", 1)
    yield
    await routes.shutdown_help_gift_catalog()


def application(role="user", authenticated=True):
    app = FastAPI()
    app.include_router(routes.router)
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4(), role=role)

    def forbidden_database():
        if authenticated:
            pytest.fail("The help example must not request a database session")
        return None

    app.dependency_overrides[get_session] = forbidden_database
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "admin"])
async def test_real_calculator_example_is_authenticated_safe_and_has_no_financial_commands(monkeypatch, role):
    gifts = [{"id": f"private-gift-{cost}", "star_count": cost} for cost in (15, 25, 50, 100)]
    calls = 0

    async def catalog():
        nonlocal calls
        calls += 1
        return gifts

    async def forbidden(*_, **__):
        pytest.fail("Help cannot create a quote or reserve money")

    monkeypatch.setattr(gift_withdrawals, "available_gifts", catalog)
    monkeypatch.setattr(gift_withdrawals, "preview_withdrawal", forbidden)
    monkeypatch.setattr(gift_withdrawals, "reserve_gift_withdrawal", forbidden)
    expected = gift_withdrawals.calculate_quote(Decimal(30), gifts)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(role)), base_url="http://test") as client:
        response = await client.get("/api/help/withdrawal-example?amount=30")
        again = await client.get("/api/help/withdrawal-example")
    assert response.status_code == again.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == again.json() == {
        "budget_af": "30.00", "gross_af": format(expected["gross_af"], ".2f"),
        "fee_af": format(expected["fee_af"], ".2f"), "payout_stars": expected["payout_stars"],
        "unspent_af": format(expected["unspent_af"], ".2f"), "fee_percent": gift_withdrawals.WITHDRAWAL_FEE_PERCENT,
        "gift_plan": [{"count": row["quantity"], "star_count": row["star_count"]} for row in expected["gift_plan"]],
    }
    assert response.json()["gross_af"] == "21.43"
    assert response.json()["fee_af"] == "6.43"
    assert response.json()["unspent_af"] == "8.57"
    assert "private-gift" not in response.text and "quote_id" not in response.text and "wallet" not in response.text
    assert calls == 1


@pytest.mark.asyncio
async def test_unauthenticated_example_is_rejected_before_catalog_lookup(monkeypatch):
    async def forbidden():
        pytest.fail("Unauthenticated requests cannot fetch gifts")

    monkeypatch.setattr(gift_withdrawals, "available_gifts", forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(authenticated=False)), base_url="http://test") as client:
        response = await client.get("/api/help/withdrawal-example")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "999999999.01", "30.001", "bad"])
async def test_invalid_example_amount_does_not_reach_catalog(monkeypatch, amount):
    async def forbidden():
        pytest.fail("Invalid budgets cannot fetch gifts")

    monkeypatch.setattr(gift_withdrawals, "available_gifts", forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application()), base_url="http://test") as client:
        response = await client.get("/api/help/withdrawal-example", params={"amount": amount})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_twenty_cold_help_requests_share_catalog_and_one_cancelled_reader_does_not_abort(monkeypatch):
    started, finish = asyncio.Event(), asyncio.Event()
    calls = 0

    async def catalog():
        nonlocal calls
        calls += 1
        started.set()
        await finish.wait()
        return [{"id": "15", "star_count": 15}]

    monkeypatch.setattr(gift_withdrawals, "available_gifts", catalog)
    pending = [asyncio.create_task(routes._help_gift_catalog()) for _ in range(20)]
    await asyncio.wait_for(started.wait(), 1)
    pending[0].cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending[0]
    finish.set()
    values = await asyncio.gather(*pending[1:])
    assert calls == 1 and all(value == [{"id": "15", "star_count": 15}] for value in values)
    assert routes._help_gift_catalog_task is None


@pytest.mark.asyncio
async def test_help_catalog_expires_after_two_minutes_and_uses_current_gift_prices(monkeypatch):
    clock = [1000]
    calls = 0

    async def catalog():
        nonlocal calls
        calls += 1
        cost = 15 if calls == 1 else 25
        return [{"id": f"private-{cost}", "star_count": cost}]

    monkeypatch.setattr(routes, "monotonic", lambda: clock[0])
    monkeypatch.setattr(gift_withdrawals, "available_gifts", catalog)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application()), base_url="http://test") as client:
        first = await client.get("/api/help/withdrawal-example?amount=40")
        clock[0] = 1119
        cached = await client.get("/api/help/withdrawal-example?amount=40")
        clock[0] = 1120
        refreshed = await client.get("/api/help/withdrawal-example?amount=40")
    assert first.json() == cached.json()
    assert first.json()["payout_stars"] == 15
    assert refreshed.json()["payout_stars"] == 25
    assert refreshed.json()["gross_af"] == "35.72"
    assert refreshed.json()["unspent_af"] == "4.28"
    assert calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "catalog", "empty"])
async def test_unavailable_example_degrades_safely_and_can_retry(monkeypatch, failure):
    calls = 0
    monkeypatch.setattr(routes, "_HELP_GIFT_CATALOG_TIMEOUT_SECONDS", .02)

    async def catalog():
        nonlocal calls
        calls += 1
        if calls > 1:
            return [{"id": "15", "star_count": 15}]
        if failure == "timeout":
            await asyncio.Event().wait()
        if failure == "catalog":
            raise HTTPException(503, "private-provider-details")
        return []

    monkeypatch.setattr(gift_withdrawals, "available_gifts", catalog)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application()), base_url="http://test") as client:
        response = await client.get("/api/help/withdrawal-example")
        assert response.status_code == 503 and "private-provider-details" not in response.text
        if failure == "empty":
            # Empty is a valid current catalogue. Retry after the short help TTL.
            routes._help_gift_catalog_expires = 0
        retry = await client.get("/api/help/withdrawal-example")
        assert retry.status_code == 200 and retry.json()["payout_stars"] == 15
    assert calls == 2


@pytest.mark.asyncio
async def test_small_budget_uses_real_minimum_and_maximum_budget_remains_bounded(monkeypatch):
    async def catalog():
        return [{"id": "15", "star_count": 15}]

    monkeypatch.setattr(gift_withdrawals, "available_gifts", catalog)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application()), base_url="http://test") as client:
        small = await client.get("/api/help/withdrawal-example?amount=21.42")
        minimum = await client.get("/api/help/withdrawal-example?amount=21.43")
        maximum = await client.get("/api/help/withdrawal-example?amount=999999999")
    assert small.status_code == 503
    assert minimum.status_code == maximum.status_code == 200
    assert minimum.json()["gross_af"] == "21.43"
    assert maximum.json()["payout_stars"] <= gift_withdrawals.get_settings().payout_nft_threshold_stars


@pytest.mark.asyncio
async def test_projection_uses_calculator_policy_instead_of_another_thirty_percent_formula(monkeypatch):
    async def catalog():
        return [{"id": "12", "star_count": 12}]

    # Isolated temporary policy proves the projection delegates to the existing
    # calculator and its current fee constant. Production policy is unchanged.
    monkeypatch.setattr(gift_withdrawals, "available_gifts", catalog)
    monkeypatch.setattr(gift_withdrawals, "WITHDRAWAL_FEE_PERCENT", 20)
    monkeypatch.setattr(gift_withdrawals, "WITHDRAWAL_NET", Decimal(".80"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application()), base_url="http://test") as client:
        response = await client.get("/api/help/withdrawal-example?amount=30")
    assert response.json() == {"budget_af": "30.00", "gross_af": "30.00", "fee_af": "6.00",
        "payout_stars": 24, "unspent_af": "0.00", "fee_percent": 20, "gift_plan": [{"count": 2, "star_count": 12}]}


@pytest.mark.asyncio
async def test_help_cache_never_replaces_fresh_catalog_checks_for_financial_quote_and_reserve(gift_db, monkeypatch):  # noqa: F811
    bridge, user, _ = gift_db
    old = await gift_withdrawals.preview_withdrawal(bridge, user, Decimal(30))
    quote_id = uuid.UUID(old["quote_id"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application()), base_url="http://test") as client:
        assert (await client.get("/api/help/withdrawal-example")).status_code == 200

        async def changed_catalog():
            return [{"id": "25", "star_count": 25}]

        monkeypatch.setattr(gift_withdrawals, "available_gifts", changed_catalog)
        # Help may keep its labelled illustration for 120 seconds.
        assert (await client.get("/api/help/withdrawal-example")).json()["payout_stars"] == 15
        with pytest.raises(HTTPException) as failure:
            await gift_withdrawals.preview_withdrawal(bridge, user, Decimal(30))
        assert failure.value.status_code == 400
        with pytest.raises(HTTPException) as failure:
            await gift_withdrawals.reserve_gift_withdrawal(bridge, user, quote_id, "")
        assert failure.value.status_code == 409
    with bridge.session.begin():
        wallet = bridge.session.scalar(select(Wallet).where(Wallet.user_id == user.id))
        assert wallet.earned_balance == 100 and wallet.earned_frozen_balance == 0
        assert bridge.session.scalar(select(func.count()).select_from(GiftWithdrawalQuote)) == 1
        assert bridge.session.scalar(select(func.count()).select_from(WithdrawalRequest)) == 0
