"""Opt-in real browser -> signed API -> isolated PostgreSQL smoke, no money."""
import asyncio
import base64
from io import BytesIO
import os
from pathlib import Path
import socket

import pytest
from PIL import Image
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
import uvicorn

from app.models import Deal, Listing, StarPayment, Wallet, WalletTransaction
from app.upload_guard import ImageUploadGuard
from test_publication_stars_postgres import app
from test_referral_bonus_postgres import isolated_pg, signed_login
from test_referrals import init_data


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("RUN_PUBLICATION_BROWSER") != "1", reason="Run after installing Playwright; dedicated CI step")
@pytest.mark.parametrize("scenario", ["publication", "vip-admin"])
async def test_real_publication_browser(scenario):
    root = Path(__file__).resolve().parents[2]
    async with isolated_pg() as (_, sessions):
        seller = await signed_login(sessions, 99801)
        buyer = await signed_login(sessions, 99802)
        application = app(sessions)
        extra_env = {}
        if scenario == "vip-admin":
            from app import promotions, admin_operations
            from app.config import Settings, get_settings
            from test_vip_admin_regressions_postgres import disputed_order
            _, _, _, control_deal, admin, _ = await disputed_order(sessions)
            _, _, _, support_deal, _, ticket = await disputed_order(sessions)
            async with sessions() as session, session.begin():
                (await session.scalar(select(Wallet).where(Wallet.user_id == seller.id))).purchased_balance = 10
            application.dependency_overrides[get_settings] = lambda: Settings(bot_token="referral-test-token", debug=False, admin_id=admin.telegram_id)
            application.include_router(promotions.router)
            application.include_router(admin_operations.router)
            extra_env = {"CRITICAL_ADMIN_AUTH": init_data(admin.telegram_id), "CRITICAL_CONTROL_DEAL": str(control_deal.id),
                         "CRITICAL_SUPPORT_DEAL": str(support_deal.id), "CRITICAL_SUPPORT_TICKET": str(ticket.id)}
        application.add_middleware(ImageUploadGuard)
        application.mount("/", StaticFiles(directory=root / "webapp", html=True))
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        server = uvicorn.Server(uvicorn.Config(application, log_level="error", lifespan="off"))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        process = None
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(.02)
            assert server.started
            with Image.new("RGB", (80, 40), "red") as image:
                exif = Image.Exif()
                exif[274] = 6
                output = BytesIO()
                image.save(output, "JPEG", exif=exif)
            env = {**os.environ, "PUBLICATION_TEST_URL": f"http://127.0.0.1:{listener.getsockname()[1]}",
                   "PUBLICATION_EXIF_JPEG": base64.b64encode(output.getvalue()).decode("ascii"),
                   "PUBLICATION_SELLER_AUTH": init_data(seller.telegram_id), "PUBLICATION_BUYER_AUTH": init_data(buyer.telegram_id), **extra_env}
            process = await asyncio.create_subprocess_exec(os.environ.get("NODE_BINARY", "node"),
                str(root / ("webapp/tests/publication-live-browser.cjs" if scenario == "publication" else "webapp/tests/vip-admin-live-browser.cjs")), env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            output, _ = await asyncio.wait_for(process.communicate(), timeout=180)
            assert process.returncode == 0, output.decode("utf-8", errors="replace")
            print(output.decode("utf-8", errors="replace"))
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(StarPayment)) == 0
                if scenario == "publication":
                    assert await session.scalar(select(func.count()).select_from(Listing)) == 2
                    assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 0
                else:
                    assert await session.scalar(select(func.count()).select_from(Listing)) == 3
                    assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "listing_promotion")) == 1
                    assert await session.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.transaction_type == "sale_income")) == 2
                    assert (await session.get(Deal, control_deal.id)).status == "completed"
                    assert (await session.get(Deal, support_deal.id)).status == "completed"
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            server.should_exit = True
            await task
            listener.close()
