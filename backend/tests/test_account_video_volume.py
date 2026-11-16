"""Real filesystem/HTTP/SQLite contract. No production storage or payments."""

import uuid
import logging

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app import account_video, account_video_volume as volume
from app.auth import get_current_user
from app.database import get_session
from app.models import AccountVideo, User
from test_account_autodelivery import (
    account_db as account_db,
    configuration as configuration,
    RequestDB,
)

MP4 = b"\x00\x00\x00\x18ftypisom" + bytes(range(256)) * 4


class VideoDB(RequestDB):
    async def rollback(self):
        self.session.rollback()


@pytest.fixture
def video_app(request, tmp_path, monkeypatch):
    bridge, seller, buyer, other, _, _ = request.getfixturevalue("account_db")
    settings = request.getfixturevalue("configuration")
    settings.account_video_storage = "volume"
    settings.account_video_volume_dir = str(tmp_path)
    settings.bot_token = "isolated-video-test-token"
    monkeypatch.setattr(account_video, "get_settings", lambda: settings)
    monkeypatch.setattr(volume, "get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(account_video.router)
    app.mount("/uploads", volume.PublicUploadFiles(directory=tmp_path))
    db = VideoDB(bridge.session)
    app.state.viewer = seller.id

    async def session():
        try:
            yield db
        finally:
            await db.rollback()

    async def user():
        return await db.get(User, app.state.viewer)

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_current_user] = user
    return app, db, settings, (seller.id, buyer.id, other.id)


async def upload(client, content=MP4, mime="video/mp4"):
    result = await client.post(
        "/api/account-videos", json={"content_type": mime, "size_bytes": len(content)}
    )
    assert result.status_code == 201, result.text
    data = result.json()
    assert data["upload_transport"] == "miniapp" and not data["upload_url"].startswith(
        "http"
    )
    response = await client.put(
        "/api" + data["upload_url"], content=content, headers={"Content-Type": mime}
    )
    return data, response


@pytest.mark.asyncio
async def test_volume_upload_playback_range_idempotency_and_public_mount_is_private(
    video_app,
):
    app, db, _, _ = video_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        data, response = await upload(client)
        assert response.status_code == 200, response.text
        assert (await client.post(f"/api/account-videos/{data['id']}/complete")).json()[
            "ready"
        ]
        play = await client.get(f"/api/account-videos/{data['id']}/play")
        assert play.status_code == 200, play.text
        assert "?access=" in play.json()["url"] and "set-cookie" not in play.headers
        assert "isolated-video-test-token" not in play.text
        url = play.json()["url"]
        result = await client.get(url, headers={"Range": "bytes=10-25"})
        assert result.status_code == 206 and result.content == MP4[10:26]
        assert result.headers["content-range"] == f"bytes 10-25/{len(MP4)}"
        assert result.headers["cache-control"] == "private, no-store"
        assert (await client.head(url)).headers["accept-ranges"] == "bytes"
        assert (
            await client.get(url, headers={"Range": "bytes=9999-"})
        ).status_code == 416
        assert (await client.get(url, headers={"Range": "bytes=-9"})).content == MP4[
            -9:
        ]
        original = (await db.get(AccountVideo, uuid.UUID(data["id"]))).object_key
        await db.rollback()
        repeat = await client.put(
            "/api" + data["upload_url"],
            content=MP4,
            headers={"Content-Type": "video/mp4"},
        )
        assert repeat.status_code == 200
        replaced = MP4[:-1] + b"x"
        result = await client.put(
            "/api" + data["upload_url"],
            content=replaced,
            headers={"Content-Type": "video/mp4"},
        )
        assert (
            result.status_code == 409
            and volume.object_path(original).read_bytes() == MP4
        )
        assert not list(volume.volume_root().glob("*.part"))
        exposed = "/uploads/.account-videos/" + original.removeprefix("volume:")
        assert (await client.get(exposed)).status_code == 404
        assert (
            await client.get(exposed.replace(".account-videos", ".ACCOUNT-VIDEOS"))
        ).status_code == 404
        assert (await client.get(url.split("?")[0])).status_code == 401
        assert (await client.get(url[:-5] + "xxxxx")).status_code == 401


@pytest.mark.asyncio
async def test_another_user_cannot_upload_and_hidden_video_requires_owner(video_app):
    app, _, _, ids = video_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        data, response = await upload(client)
        assert response.status_code == 200
        app.state.viewer = ids[2]
        assert (
            await client.get(f"/api/account-videos/{data['id']}/play")
        ).status_code == 404
        assert (
            await client.put(
                "/api" + data["upload_url"],
                content=MP4,
                headers={"Content-Type": "video/mp4"},
            )
        ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mime,content",
    [
        ("video/mp4", MP4),
        ("video/quicktime", MP4[:8] + b"qt  " + MP4[12:]),
        ("video/webm", b"\x1aE\xdf\xa3webm" + b"0" * 100),
    ],
    ids=["mp4", "iphone-mov", "webm"],
)
async def test_supported_containers(video_app, mime, content):
    app, _, _, _ = video_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        _, result = await upload(client, content, mime)
        assert result.status_code == 200, result.text


@pytest.mark.asyncio
async def test_bad_incomplete_and_oversize_files_leave_no_private_files(video_app):
    app, _, settings, _ = video_app
    settings.account_video_max_bytes = 2048
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        _, bad = await upload(client, b"this is not a video")
        assert bad.status_code == 422
        start = (
            await client.post(
                "/api/account-videos",
                json={"content_type": "video/mp4", "size_bytes": len(MP4)},
            )
        ).json()
        assert (
            await client.post(f"/api/account-videos/{start['id']}/complete")
        ).status_code == 409
        result = await client.put(
            "/api" + start["upload_url"],
            content=MP4[:20],
            headers={"Content-Type": "video/mp4"},
        )
        assert result.status_code == 422
        result = await client.post(
            "/api/account-videos",
            json={"content_type": "video/mp4", "size_bytes": 2049},
        )
        assert result.status_code == 413
        assert not list(volume.volume_root().rglob("*.part"))


def test_storage_auto_detects_only_real_mount_and_token_expiry(video_app, monkeypatch):
    _, _, settings, ids = video_app
    settings.account_video_storage = "auto"
    assert volume.use_volume()
    settings.account_s3_endpoint = "https://configured-s3.example"
    assert not volume.use_volume()
    settings.account_video_volume_dir = settings.railway_volume_mount_path = ""
    with pytest.raises(HTTPException) as error:
        volume.volume_root()
    assert error.value.status_code == 503
    with pytest.raises(HTTPException):
        volume.object_path("volume:../../private")
    from types import SimpleNamespace

    video = SimpleNamespace(id=uuid.uuid4(), object_key="volume:videos/test")
    token = volume.playback_token(video, SimpleNamespace(id=ids[0]))
    assert volume.playback_viewer(token, video) == ids[0]
    monkeypatch.setattr(volume, "PLAYBACK_TTL", -1)
    with pytest.raises(HTTPException):
        volume.playback_viewer(token, video)


def test_access_log_never_retains_video_capability():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %s',
        (
            "local",
            "GET",
            "/api/account-videos/test/stream?access=private-capability",
            "1.1",
            206,
        ),
        None,
    )
    assert volume.VideoAccessLogFilter().filter(record)
    assert (
        "private-capability" not in record.getMessage()
        and "/stream" in record.getMessage()
    )
