"""Signed Mini App -> real isolated PG + persistent-file video; no production."""

import asyncio
import os
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app import account_video, account_video_volume as volume, account_sales
from app.models import AccountVideo, Listing, WalletTransaction
from test_account_autodelivery import configuration as configuration, payload
from test_account_autodelivery_postgres import media
from test_catalog_and_acceptance_postgres import client_app, headers
from test_referral_bonus_postgres import isolated_pg, signed_login
from test_referrals import init_data
from test_account_video_volume import MP4


@pytest.fixture
def volume_settings(request, tmp_path, monkeypatch):
    settings = request.getfixturevalue("configuration")
    settings.account_video_storage = "auto"
    settings.account_video_volume_dir = ""
    settings.railway_volume_mount_path = str(tmp_path)
    settings.bot_token = "referral-test-token"
    monkeypatch.setattr(account_video, "get_settings", lambda: settings)
    monkeypatch.setattr(volume, "get_settings", lambda: settings)
    return settings


@pytest.mark.asyncio
@pytest.mark.parametrize("game", ["car_parking_1", "car_parking_2"])
async def test_parallel_upload_signed_buyer_acl_hide_and_restart(volume_settings, game):
    async with isolated_pg() as (_, sessions):
        seller, buyer = (
            await signed_login(sessions, 7601),
            await signed_login(sessions, 7602),
        )
        _, cover = await media(sessions, seller)
        app = client_app(sessions)
        app.include_router(account_video.router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            result = await client.post(
                "/api/account-videos",
                headers=headers(seller),
                json={"content_type": "video/mp4", "size_bytes": len(MP4)},
            )
            assert result.status_code == 201, result.text
            data = result.json()

            async def send():
                return await client.put(
                    "/api" + data["upload_url"],
                    content=MP4,
                    headers={**headers(seller), "Content-Type": "video/mp4"},
                )

            responses = await asyncio.wait_for(
                asyncio.gather(*(send() for _ in range(8))), 30
            )
            assert all(response.status_code == 200 for response in responses), [
                r.text for r in responses
            ]
            assert not list(volume.volume_root().glob("*.part"))
            assert len(list(volume.volume_root().glob("videos/*/*"))) == 1
            async with sessions() as session:
                video = await session.get(AccountVideo, uuid.UUID(data["id"]))
                publication = payload(video, cover, game_version=game)
            async with sessions() as session:
                item = await account_sales.publish(session, seller, publication)
            play = await client.get(
                f"/api/account-videos/{video.id}/play", headers=headers(buyer)
            )
            assert play.status_code == 200, play.text
            assert "?access=" in play.json()["url"] and "set-cookie" not in play.headers
            url = play.json()["url"]
            part = await client.get(url, headers={"Range": "bytes=20-80"})
            assert part.status_code == 206 and part.content == MP4[20:81]
            # A restarted HTTP app still reads the same immutable volume file.
            restarted = client_app(sessions)
            restarted.include_router(account_video.router)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(restarted),
                base_url="http://test",
            ) as after:
                assert (await after.get(url)).content == MP4
            async with sessions() as session, session.begin():
                (await session.get(Listing, item.id)).status = "paused"
            assert (await client.get(url)).status_code == 404
            assert (
                await client.get(
                    f"/api/account-videos/{video.id}/play", headers=headers(buyer)
                )
            ).status_code == 404
            async with sessions() as session:
                assert (
                    await session.scalar(
                        select(func.count()).select_from(WalletTransaction)
                    )
                    == 0
                )


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_ACCOUNT_VIDEO_BROWSER") != "1",
    reason="Dedicated real media browser step",
)
async def test_signed_buyer_plays_real_volume_webm(volume_settings, tmp_path):
    from account_video_fixture import make_video
    from test_account_video_browser import run_browser

    file = make_video(tmp_path)
    content = file.read_bytes()
    async with isolated_pg() as (_, sessions):
        seller, buyer = (
            await signed_login(sessions, 7701),
            await signed_login(sessions, 7702),
        )
        _, cover = await media(sessions, seller)
        app = client_app(sessions)
        app.include_router(account_video.router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            result = await client.post(
                "/api/account-videos",
                headers=headers(seller),
                json={"content_type": "video/webm", "size_bytes": len(content)},
            )
            assert result.status_code == 201, result.text
            data = result.json()
            result = await client.put(
                "/api" + data["upload_url"],
                content=content,
                headers={**headers(seller), "Content-Type": "video/webm"},
            )
            assert result.status_code == 200, result.text
        async with sessions() as session:
            video = await session.get(AccountVideo, uuid.UUID(data["id"]))
            publication = payload(video, cover)
        async with sessions() as session:
            await account_sales.publish(session, seller, publication)
        await run_browser(app, video.id, init_data(buyer.telegram_id))
