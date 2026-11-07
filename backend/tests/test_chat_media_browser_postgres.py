"""Real UI -> signed API -> isolated PG. No Telegram traffic or real payments."""

import asyncio
import base64
import os
import socket
from pathlib import Path

import pytest
import uvicorn
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app.chat_media import router
from app.deal_reminders import router as reminders_router
from app.models import PrivateChatImage, Wallet, WalletTransaction
from app.upload_guard import ImageUploadGuard
from test_catalog_and_acceptance_postgres import client_app
from test_private_chat_photos import photo
from test_referral_bonus_postgres import isolated_pg
from test_referrals import init_data
from test_seller_orders_postgres import paid_order


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_CHAT_BROWSER") != "1", reason="Dedicated CI browser step"
)
@pytest.mark.parametrize("width", [320, 390, 430])
async def test_live_chat_photos(width):
    root = Path(__file__).resolve().parents[2]
    async with isolated_pg() as (_, sessions):
        buyer, seller, _, deal = await paid_order(sessions)
        app = client_app(sessions)
        app.include_router(router)
        app.include_router(reminders_router)
        app.add_middleware(ImageUploadGuard)
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
                "CHAT_TEST_URL": f"http://127.0.0.1:{listener.getsockname()[1]}",
                "CHAT_TEST_DEAL": str(deal.id),
                "CHAT_TEST_WIDTH": str(width),
                "CHAT_TEST_PHOTO": base64.b64encode(photo()).decode(),
                "CHAT_SELLER_AUTH": init_data(seller.telegram_id),
                "CHAT_BUYER_AUTH": init_data(buyer.telegram_id),
            }
            process = await asyncio.create_subprocess_exec(
                os.environ.get("NODE_BINARY", "node"),
                str(root / "webapp/tests/chat-live-browser.cjs"),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await asyncio.wait_for(process.communicate(), 150)
            assert process.returncode == 0, output.decode("utf-8", errors="replace")
            print(output.decode("utf-8", errors="replace"))
            async with sessions() as session:
                assert (
                    await session.scalar(
                        select(func.count()).select_from(PrivateChatImage)
                    )
                    == 3
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(WalletTransaction)
                        .where(WalletTransaction.transaction_type == "sale_income")
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(Wallet).where(Wallet.user_id == buyer.id)
                    )
                ).frozen_balance == 100
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            server.should_exit = True
            await task
            listener.close()
