"""Private, bounded account videos on the existing persistent Railway volume.

No credentials or videos in public uploads/DB blobs. Existing S3 assets keep
their original provider; volume keys have an explicit reserved prefix.
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

import anyio
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from .config import get_settings

UPLOAD_SLOTS = asyncio.Semaphore(2)
PLAYBACK_TTL = 3600


class VideoAccessLogFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn access args: client, method, path+query, HTTP version, status.
        # Short-lived playback capabilities are not account credentials, but
        # should not be retained in application access logs either.
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            if args[2].startswith("/api/account-videos/") and "/stream?" in args[2]:
                record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


class PublicUploadFiles(StaticFiles):
    async def get_response(self, path, scope):
        # The production volume is the existing legacy /uploads mount. Never
        # let the old public route bypass account-video authorization.
        if ".account-videos" in path.replace("\\", "/").lower().split("/"):
            raise HTTPException(404, "Not found")
        return await super().get_response(path, scope)


def volume_root():
    settings = get_settings()
    base = settings.account_video_volume_dir or settings.railway_volume_mount_path
    if not base or not Path(base).is_absolute() or not Path(base).is_dir():
        raise HTTPException(503, "Постоянное хранилище видео не настроено")
    root = Path(base).resolve() / ".account-videos"
    if root.is_symlink():
        raise HTTPException(503, "Хранилище видео недоступно")
    return root


def use_volume():
    settings = get_settings()
    return settings.account_video_storage == "volume" or (
        settings.account_video_storage == "auto" and not settings.account_s3_endpoint
    )


def object_path(key):
    if not re.fullmatch(r"volume:videos/[a-f0-9]{32}/[a-f0-9]{64}", key):
        raise HTTPException(404, "Видео недоступно")
    root = volume_root()
    path = root / key.removeprefix("volume:")
    if not path.resolve().is_relative_to(root):
        raise HTTPException(404, "Видео недоступно")
    return path


def valid_container(mime, header):
    header = bytes(header)
    return bool(
        (
            mime in {"video/mp4", "video/quicktime"}
            and len(header) >= 12
            and header[4:8] == b"ftyp"
            and header[8:12] not in {b"heic", b"heix", b"avif", b"mif1", b"hevc"}
        )
        or (
            mime == "video/webm"
            and header.startswith(b"\x1aE\xdf\xa3")
            and b"webm" in header[:4096]
        )
    )


def playback_cipher():
    token = get_settings().bot_token
    if not token:
        raise HTTPException(503, "Просмотр видео временно недоступен")
    return Fernet(
        base64.urlsafe_b64encode(
            hashlib.sha256(
                b"autoflow-account-video-playback-v1:" + token.encode()
            ).digest()
        )
    )


def playback_token(video, user):
    return (
        playback_cipher()
        .encrypt(
            json.dumps(
                {
                    "video": str(video.id),
                    "viewer": str(user.id),
                    "asset": hashlib.sha256(video.object_key.encode()).hexdigest(),
                }
            ).encode()
        )
        .decode()
    )


def playback_viewer(token, video):
    try:
        if not token or len(token) > 2048:
            raise ValueError()
        value = json.loads(playback_cipher().decrypt(token.encode(), ttl=PLAYBACK_TTL))
        if (
            value["video"] != str(video.id)
            or value["asset"] != hashlib.sha256(video.object_key.encode()).hexdigest()
        ):
            raise ValueError()
        return uuid.UUID(value["viewer"])
    except (InvalidToken, ValueError, KeyError, TypeError):
        raise HTTPException(
            401, "Откройте видео из карточки аккаунта повторно"
        ) from None


async def receive_video(request: Request, video_id, size, mime):
    """Return a validated temporary file, never buffer the entire upload."""
    try:
        length = request.headers.get("content-length")
        if length is not None and int(length) != size:
            raise ValueError()
    except ValueError:
        raise HTTPException(
            422, "Размер файла изменился. Выберите видео повторно"
        ) from None
    if request.headers.get("content-type", "").split(";")[0] != mime:
        raise HTTPException(415, "Выберите видео MP4, MOV или WebM")
    root = volume_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    free = (await run_in_threadpool(shutil.disk_usage, root)).free
    # Preserve disk space for legacy car photos and incomplete concurrent writes.
    if free < size + get_settings().account_video_max_bytes + 256 * 1024 * 1024:
        raise HTTPException(507, "Хранилище заполнено. Обратитесь в поддержку")
    temporary = root / f"upload-{video_id.hex}-{uuid.uuid4().hex}.part"
    try:
        count, header, digest = 0, bytearray(), hashlib.sha256()
        async with await anyio.open_file(temporary, "xb") as output:
            async for chunk in request.stream():
                count += len(chunk)
                if count > size or count > get_settings().account_video_max_bytes:
                    raise HTTPException(413, "Видео превышает разрешённый размер")
                if len(header) < 65536:
                    header.extend(chunk[: 65536 - len(header)])
                digest.update(chunk)
                await output.write(chunk)
            await output.flush()
            await run_in_threadpool(os.fsync, output.wrapped.fileno())
        if count != size or not valid_container(mime, header):
            raise HTTPException(
                422, "Видео не подтверждено. Выберите полный файл MP4, MOV или WebM"
            )
        return temporary, f"volume:videos/{video_id.hex}/{digest.hexdigest()}"
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
