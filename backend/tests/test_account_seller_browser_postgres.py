"""Seller UI -> signed API -> PostgreSQL -> real queued FFmpeg -> buyer UI.

Only the unpredictable schema in REFERRAL_TEST_DATABASE_URL and tmp_path are
written. No Telegram API calls, Stars checkout, or production funds are used.
"""

import asyncio
import os
import socket
from pathlib import Path

import pytest
import uvicorn
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app import account_pins, account_video, account_video_processing as processing
from app import account_video_volume as volume
from app.models import (
    AccountGrant,
    AccountPin,
    AccountSecret,
    AccountVideo,
    ConversationMessage,
    Deal,
    Listing,
    ListingImage,
    Wallet,
    WalletTransaction,
)
from app.support_media import router as support_router
from account_video_fixture import make_video
from test_account_autodelivery import configuration  # noqa: F401 -- pytest fixture
from test_account_video_processing import binaries
from test_catalog_and_acceptance_postgres import client_app
from test_private_chat_photos import photo
from test_referral_bonus_postgres import isolated_pg, signed_login
from test_referrals import init_data


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_ACCOUNT_BROWSER") != "1", reason="Dedicated real media/PG step"
)
async def test_real_seller_form_upload_process_publish_and_buyer_chat(
    request, monkeypatch, tmp_path
):
    settings = request.getfixturevalue("configuration")
    ffmpeg, ffprobe = binaries()
    root = Path(__file__).resolve().parents[2]
    settings.account_video_storage = "volume"
    settings.account_video_volume_dir = str(tmp_path)
    settings.account_video_processing_enabled = True
    settings.ffmpeg_binary, settings.ffprobe_binary = ffmpeg, ffprobe
    settings.bot_token = "referral-test-token"  # Isolated playback signature.
    for module in (account_video, volume, processing):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    source = make_video(tmp_path)
    cover = tmp_path / "account-cover.png"
    cover.write_bytes(photo())

    async with isolated_pg() as (_, sessions):
        seller, buyer = (
            await signed_login(sessions, 5751),
            await signed_login(sessions, 5752),
        )
        async with sessions() as session, session.begin():
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == buyer.id))
            wallet.purchased_balance = 200

        app = client_app(sessions)
        app.include_router(account_pins.router)
        app.include_router(support_router)
        app.mount("/uploads", volume.PublicUploadFiles(directory=tmp_path))
        app.mount("/", StaticFiles(directory=root / "webapp", html=True))
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        server_task = asyncio.create_task(server.serve(sockets=[listener]))

        async def isolated_worker():
            while True:
                # Production queue/codec, scoped session factory; never SessionLocal.
                worked = await processing.process_one(sessions)
                await asyncio.sleep(0.02 if worked else 0.1)

        worker_task = asyncio.create_task(isolated_worker())
        process = None
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.02)
            assert server.started, "Isolated HTTP server did not start"
            process = await asyncio.create_subprocess_exec(
                os.environ.get("NODE_BINARY", "node"),
                str(root / "webapp/tests/account-seller-live-browser.cjs"),
                env={
                    **os.environ,
                    "ACCOUNT_TEST_URL": f"http://127.0.0.1:{listener.getsockname()[1]}",
                    "ACCOUNT_SELLER_AUTH": init_data(seller.telegram_id),
                    "ACCOUNT_BUYER_AUTH": init_data(buyer.telegram_id),
                    "ACCOUNT_TEST_COVER": str(cover),
                    "ACCOUNT_TEST_VIDEO": str(source),
                },
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await asyncio.wait_for(process.communicate(), 180)
            assert process.returncode == 0, output.decode("utf-8", errors="replace")
            print(output.decode("utf-8", errors="replace"))
            if worker_task.done():
                worker_task.result()  # Never hide worker/DB errors behind a UI timeout.

            async with sessions() as session:
                items = list((await session.scalars(select(Listing))).all())
                assert len(items) == 1
                item = items[0]
                assert item.product_kind == "account" and item.game_version == "car_parking_2"
                assert item.seller_id == seller.id and item.price_af_coins == 100
                assert item.pinned is False
                video = await session.get(AccountVideo, item.video_asset_id)
                assert video.owner_id == seller.id and video.ready
                assert video.processing_status == "ready" and video.processed_key
                assert video.processing_meta["codec"] == "h264"
                assert video.processing_meta["progress"] == 100
                assert 29 <= video.processing_meta["duration"] <= 31
                assert volume.object_path(video.processed_key).is_file()
                assert await session.scalar(select(func.count()).select_from(AccountVideo)) == 1
                image = await session.scalar(select(ListingImage).where(ListingImage.listing_id == item.id))
                assert image.url.startswith("/api/media/")
                secret = await session.get(AccountSecret, item.id)
                assert secret.ciphertext and b"seller-ui@example.test" not in secret.ciphertext
                assert b"seller-ui-private-password" not in secret.ciphertext
                deal = await session.scalar(select(Deal).where(Deal.listing_id == item.id))
                assert deal.buyer_id == buyer.id and deal.status == "transfer_in_progress"
                grant = await session.get(AccountGrant, deal.id)
                assert grant.ciphertext and b"seller-ui-private-password" not in grant.ciphertext
                assert await session.scalar(select(func.count()).select_from(ConversationMessage)) >= 1
                assert await session.scalar(select(func.count()).select_from(AccountPin)) == 0
                assert await session.scalar(
                    select(func.count()).select_from(WalletTransaction).where(
                        WalletTransaction.transaction_type.in_(("account_publication", "sale_income"))
                    )
                ) == 0, "First publication is free and buyer has not confirmed settlement"
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)
            server.should_exit = True
            await server_task
            listener.close()
