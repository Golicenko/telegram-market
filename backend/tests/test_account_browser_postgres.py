"""Browser -> signed API -> isolated PG, with a scoped 61s test clock only."""

import asyncio
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import uvicorn
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app import account_pins, account_sales
from app.models import Deal, WalletTransaction
from app.support_media import router as support_router
from test_account_autodelivery import configuration, payload  # noqa: F401 -- pytest fixture
from test_account_autodelivery_postgres import media
from test_catalog_and_acceptance_postgres import client_app
from test_referral_bonus_postgres import isolated_pg, signed_login
from test_referrals import init_data

pytestmark = pytest.mark.usefixtures("configuration")


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_ACCOUNT_BROWSER") != "1", reason="Dedicated CI browser step"
)
@pytest.mark.parametrize("width", [320, 390, 430])
async def test_signed_account_purchase_and_private_card(width, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    async with isolated_pg() as (_, sessions):
        seller, buyer = (
            await signed_login(sessions, 5701),
            await signed_login(sessions, 5702),
        )
        video, cover = await media(sessions, seller)
        await media(sessions, buyer)
        async with sessions() as session:
            item = await account_sales.publish(session, seller, payload(video, cover))
        deliver = account_sales.deliver_locked

        async def earlier_clock(session, deal, values):
            await deliver(session, deal, values)
            deal.transfer_started_at = datetime.now(UTC) - timedelta(seconds=61)

        monkeypatch.setattr(account_sales, "deliver_locked", earlier_clock)
        app = client_app(sessions)
        app.include_router(account_pins.router)
        app.include_router(support_router)
        app.mount("/", StaticFiles(directory=root / "webapp", html=True))
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        process = None
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.02)
            env = {
                **os.environ,
                "ACCOUNT_TEST_URL": f"http://127.0.0.1:{listener.getsockname()[1]}",
                "ACCOUNT_TEST_WIDTH": str(width),
                "ACCOUNT_TEST_LISTING": str(item.id),
                "ACCOUNT_BUYER_AUTH": init_data(buyer.telegram_id),
                "ACCOUNT_SELLER_AUTH": init_data(seller.telegram_id),
            }
            process = await asyncio.create_subprocess_exec(
                os.environ.get("NODE_BINARY", "node"),
                str(root / "webapp/tests/account-live-browser.cjs"),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await asyncio.wait_for(process.communicate(), 150)
            assert process.returncode == 0, output.decode("utf-8", errors="replace")
            print(output.decode("utf-8", errors="replace"))
            async with sessions() as session:
                deal = await session.scalar(
                    select(Deal).where(Deal.listing_id == item.id)
                )
                assert deal.status == "completed"
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(WalletTransaction)
                        .where(WalletTransaction.transaction_type == "sale_income")
                    )
                    == 1
                )
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            server.should_exit = True
            await task
            listener.close()
