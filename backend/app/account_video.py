"""Account video upload and playback, on the existing volume or configured S3."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from starlette.responses import FileResponse

from .account_sales import router, ready, is_enabled
from .auth import get_current_user
from .config import get_settings
from .database import AsyncSession, get_session
from .models import AccountVideo, Deal, Listing, User
from .account_video_volume import (
    PLAYBACK_TTL,
    object_path,
    playback_token,
    playback_viewer,
    receive_video,
    use_volume,
    valid_container,
    volume_root,
    upload_slots,
)


def storage():
    settings = get_settings()
    endpoint = urlparse(settings.account_s3_endpoint)
    if (
        endpoint.scheme != "https"
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or not all(
            (
                settings.account_s3_bucket,
                settings.account_s3_access_key,
                settings.account_s3_secret_key,
            )
        )
    ):
        raise HTTPException(503, "Внешнее хранилище видео не настроено")
    return boto3.client(
        "s3",
        endpoint_url=settings.account_s3_endpoint,
        region_name=settings.account_s3_region,
        aws_access_key_id=settings.account_s3_access_key,
        aws_secret_access_key=settings.account_s3_secret_key,
        config=Config(
            signature_version="s3v4",
            connect_timeout=5,
            read_timeout=15,
            retries={"max_attempts": 1},
        ),
    ), settings.account_s3_bucket


class VideoStart(BaseModel):
    content_type: str = Field(pattern="^video/(mp4|webm|quicktime)$")
    size_bytes: int = Field(gt=0)


@router.post("/account-videos", status_code=201)
async def begin_video(
    payload: VideoStart,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ready()
    from .account_video_processing import tools_ready

    if get_settings().account_video_processing_enabled and not tools_ready():
        raise HTTPException(503, "Обработка видео не настроена. Обратитесь в поддержку")
    if payload.size_bytes > get_settings().account_video_max_bytes:
        raise HTTPException(413, "Видео превышает разрешённый размер")
    on_volume = use_volume()
    if on_volume:
        volume_root()  # Fail before creating a record on an ephemeral container.
    else:
        client, bucket = storage()
    video = AccountVideo(
        id=uuid.uuid4(),
        owner_id=user.id,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        processing_status="uploading"
        if get_settings().account_video_processing_enabled
        else None,
        object_key=f"volume:pending/{uuid.uuid4().hex}"
        if on_volume
        else f"account-uploads/{user.id}/{uuid.uuid4()}",
    )
    url = (
        f"/account-videos/{video.id}/content"
        if on_volume
        else await run_in_threadpool(
            client.generate_presigned_url,
            "put_object",
            Params={
                "Bucket": bucket,
                "Key": video.object_key,
                "ContentType": payload.content_type,
                "ContentLength": payload.size_bytes,
            },
            ExpiresIn=300,
        )
    )
    async with session.begin():
        await session.scalar(
            select(User.id).where(User.id == user.id).with_for_update()
        )
        pending = await session.scalar(
            select(func.count())
            .select_from(AccountVideo)
            .where(
                AccountVideo.owner_id == user.id,
                AccountVideo.processing_status.in_(
                    ("uploading", "queued", "processing")
                ),
                AccountVideo.created_at > datetime.now(UTC) - timedelta(hours=1),
            )
        )
        daily = await session.scalar(
            select(func.count())
            .select_from(AccountVideo)
            .where(
                AccountVideo.owner_id == user.id,
                AccountVideo.processing_status.is_not(None),
                AccountVideo.created_at > datetime.now(UTC) - timedelta(days=1),
            )
        )
        if pending >= 3 or daily >= get_settings().account_video_daily_limit:
            raise HTTPException(
                429,
                "Слишком много видео в обработке. Дождитесь завершения или повторите позже.",
            )
        session.add(video)
    return {
        "id": video.id,
        "upload_url": url,
        "upload_transport": "miniapp" if on_volume else "s3",
        "content_type": payload.content_type,
        "max_bytes": get_settings().account_video_max_bytes,
    }


def verify_and_freeze(client, bucket, video):
    try:
        head = client.head_object(Bucket=bucket, Key=video.object_key)
        if (
            head["ContentLength"] != video.size_bytes
            or head["ContentLength"] > get_settings().account_video_max_bytes
        ):
            raise ValueError()
        response = client.get_object(
            Bucket=bucket,
            Key=video.object_key,
            Range="bytes=0-65535",
            IfMatch=head["ETag"],
        )
        try:
            header = response["Body"].read(65536)
        finally:
            response["Body"].close()
        if not valid_container(video.content_type, header):
            raise ValueError()
        # Freeze a separate key not covered by the still-valid upload URL.
        final = f"account-videos/{video.id}/{uuid.uuid4()}"
        client.copy_object(
            Bucket=bucket,
            Key=final,
            CopySource={"Bucket": bucket, "Key": video.object_key},
            CopySourceIfMatch=head["ETag"],
            MetadataDirective="REPLACE",
            ContentType=video.content_type,
            ContentDisposition="inline",
        )
        return final
    except Exception:
        # Provider exceptions can include signed URLs/keys. Never expose/log them.
        raise HTTPException(
            422, "Видео не подтверждено. Проверьте файл и завершение загрузки"
        ) from None


@router.post("/account-videos/{video_id}/complete")
async def complete_video(
    video_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ready()
    async with session.begin():
        video = await session.scalar(
            select(AccountVideo).where(AccountVideo.id == video_id).with_for_update()
        )
        if not video or video.owner_id != user.id:
            raise HTTPException(404, "Видео не найдено")
        if video.processing_status in {"expired", "expiring"}:
            raise HTTPException(
                409, "Срок хранения загрузки истёк. Выберите видео заново"
            )
        if not video.ready:
            if video.processing_status in {
                "queued",
                "processing",
                "failed",
                "cancelled",
            }:
                return video_state(video)
            if video.object_key.startswith("volume:"):
                raise HTTPException(409, "Сначала завершите загрузку видео")
            client, bucket = storage()
            upload_key = video.object_key
            video.object_key = await run_in_threadpool(
                verify_and_freeze, client, bucket, video
            )
            video.ready = video.processing_status is None
            if video.processing_status == "uploading":
                video.processing_status = "queued"
                video.processing_meta = {
                    **(video.processing_meta or {}),
                    "upload_key": upload_key,
                }
    return video_state(video)


def video_state(video):
    meta = video.processing_meta or {}
    return {
        "id": video.id,
        "ready": video.ready,
        "status": video.processing_status or ("ready" if video.ready else "uploading"),
        "progress": meta.get("progress", 0),
        "error": meta.get("error"),
        "output_bytes": meta.get("output_bytes"),
    }


@router.get("/account-videos/{video_id}/status")
async def video_status(
    video_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    video = await session.get(AccountVideo, video_id)
    if not video or video.owner_id != user.id:
        raise HTTPException(404, "Видео не найдено")
    return video_state(video)


@router.post("/account-videos/{video_id}/cancel")
async def cancel_video(
    video_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        video = await session.scalar(
            select(AccountVideo).where(AccountVideo.id == video_id).with_for_update()
        )
        if not video or video.owner_id != user.id:
            raise HTTPException(404, "Видео не найдено")
        if not video.ready:
            video.processing_status = "cancelled"
    return video_state(video)


@router.post("/account-videos/{video_id}/retry")
async def retry_video(
    video_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ready()
    async with session.begin():
        video = await session.scalar(
            select(AccountVideo).where(AccountVideo.id == video_id).with_for_update()
        )
        if not video or video.owner_id != user.id:
            raise HTTPException(404, "Видео не найдено")
        if video.processing_status == "failed":
            if (video.processing_meta or {}).get("attempts", 0) >= 3:
                raise HTTPException(409, "Выберите другой файл видео")
            video.processing_status = "queued"
            video.processing_meta = {
                **(video.processing_meta or {}),
                "progress": 0,
                "error": None,
            }
    return video_state(video)


@router.put("/account-videos/{video_id}/content")
async def upload_video(
    video_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ready()
    owner = user.id
    video = await session.get(AccountVideo, video_id)
    if (
        not video
        or video.owner_id != owner
        or not video.object_key.startswith("volume:")
    ):
        raise HTTPException(404, "Видео не найдено")
    size, mime = video.size_bytes, video.content_type
    if not size or size > get_settings().account_video_max_bytes:
        raise HTTPException(413, "Видео превышает разрешённый размер")
    # Do not occupy a DB transaction/connection during a slow mobile upload.
    await session.rollback()
    slots = upload_slots(request)
    try:
        await asyncio.wait_for(slots.acquire(), 5)
    except TimeoutError:
        raise HTTPException(
            429, "Загрузка видео занята. Повторите через несколько секунд"
        ) from None
    temporary = None
    try:
        temporary, key = await asyncio.wait_for(
            receive_video(request, video_id, size, mime), 300
        )
        async with session.begin():
            video = await session.scalar(
                select(AccountVideo)
                .where(AccountVideo.id == video_id)
                .with_for_update()
            )
            if not video or video.owner_id != owner:
                raise HTTPException(404, "Видео не найдено")
            if video.processing_status in {"cancelled", "expired", "expiring"}:
                raise HTTPException(409, "Загрузка отменена")
            if (
                video.object_key.startswith("volume:videos/")
                and video.object_key != key
            ):
                raise HTTPException(
                    409, "Загруженное видео нельзя заменить. Создайте новое"
                )
            target = object_path(key)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not target.exists():
                temporary.replace(target)
            video.object_key = key
            if video.processing_status == "uploading":
                video.processing_status = "queued"
            video.ready = (
                video.ready
                or video.processing_status is None
                or video.processing_status == "ready"
            )
        return video_state(video)
    except TimeoutError:
        raise HTTPException(
            408, "Загрузка заняла слишком много времени. Повторите попытку"
        ) from None
    except ClientDisconnect:
        raise HTTPException(
            400, "Соединение прервано во время загрузки видео"
        ) from None
    except OSError as error:
        # Never log file paths, cookies, URLs or account credentials.
        logging.getLogger("autoflow.api").warning(
            "account_video_storage_error video=%s errno=%s", video_id, error.errno
        )
        raise HTTPException(
            503, "Не удалось сохранить видео. Повторите позже"
        ) from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        slots.release()


async def require_playback(session, video, user):
    listing = await session.scalar(
        select(Listing)
        .where(
            Listing.video_asset_id == video.id,
            Listing.deleted_at.is_(None),
            Listing.status.in_(("active", "reserved", "sold")),
        )
        .limit(1)
    )
    if not is_enabled() and video.owner_id != user.id and user.role != "admin":
        # A public preview is hidden during the pause, but an existing buyer
        # retains access to the purchased item's evidence in the deal.
        listing = await session.scalar(select(Listing).join(Deal, Deal.listing_id == Listing.id).where(
            Listing.video_asset_id == video.id,
            Deal.buyer_id == user.id,
        ).limit(1))
    if (
        not video.ready
        or user.is_blocked
        or (video.owner_id != user.id and not listing and user.role != "admin")
    ):
        raise HTTPException(404, "Видео недоступно")


@router.get("/account-videos/{video_id}/play")
async def play_video(
    video_id: uuid.UUID,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    video = await session.get(AccountVideo, video_id)
    if not video:
        raise HTTPException(404, "Видео недоступно")
    await require_playback(session, video, user)
    key = video.processed_key or video.object_key
    response.headers["Cache-Control"] = "private, no-store"
    if key.startswith("volume:"):
        if not object_path(key).is_file():
            raise HTTPException(404, "Файл видео недоступен. Обратитесь в поддержку")
        path = f"/api/account-videos/{video.id}/stream"
        # Native <video> cannot send initData headers. A short-lived capability
        # works even with third-party cookies blocked in Telegram Web embeds.
        # It is scoped to this viewer/immutable video, never game credentials.
        return {"url": f"{path}?access={playback_token(video, user)}"}
    client, bucket = storage()
    url = await run_in_threadpool(
        client.generate_presigned_url,
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=PLAYBACK_TTL,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return {"url": url}


@router.api_route("/account-videos/{video_id}/stream", methods=["GET", "HEAD"])
async def stream_video(
    video_id: uuid.UUID,
    request: Request,
    access: str | None = Query(default=None, max_length=2048),
    session: AsyncSession = Depends(get_session),
):
    requested_range = request.headers.get("range", "")
    if len(requested_range) > 128 or "," in requested_range:
        raise HTTPException(416, "Запрошенный диапазон видео недоступен")
    video = await session.get(AccountVideo, video_id)
    if not video or not video.ready or not video.object_key.startswith("volume:"):
        raise HTTPException(404, "Видео недоступно")
    viewer = playback_viewer(access, video)
    user = await session.get(User, viewer)
    if not user:
        raise HTTPException(401, "Откройте видео из карточки аккаунта повторно")
    await require_playback(session, video, user)
    path = object_path(video.processed_key or video.object_key)
    if not path.is_file():
        raise HTTPException(404, "Файл видео недоступен")
    # Release DB connection before streaming the body. Starlette implements
    # byte ranges/206/416, so seeking does not download the entire video again.
    mime = "video/mp4" if video.processed_key else video.content_type
    await session.rollback()
    return FileResponse(
        path,
        media_type=mime,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )
