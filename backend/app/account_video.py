"""Direct S3-compatible video upload; Railway never receives the video body."""

import uuid
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from .account_sales import router, ready
from .auth import get_current_user
from .config import get_settings
from .database import AsyncSession, get_session
from .models import AccountVideo, Listing, User


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
    content_type: str = Field(pattern="^video/(mp4|webm)$")
    size_bytes: int = Field(gt=0)


@router.post("/account-videos", status_code=201)
async def begin_video(
    payload: VideoStart,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ready()
    if payload.size_bytes > get_settings().account_video_max_bytes:
        raise HTTPException(413, "Видео превышает разрешённый размер")
    client, bucket = storage()
    video = AccountVideo(
        id=uuid.uuid4(),
        owner_id=user.id,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        object_key=f"account-uploads/{user.id}/{uuid.uuid4()}",
    )
    url = await run_in_threadpool(
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
    async with session.begin():
        session.add(video)
    return {
        "id": video.id,
        "upload_url": url,
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
        valid = (
            video.content_type == "video/mp4"
            and len(header) >= 12
            and header[4:8] == b"ftyp"
            and header[8:12] not in {b"heic", b"heix", b"avif", b"mif1", b"hevc"}
        ) or (
            video.content_type == "video/webm"
            and header.startswith(b"\x1aE\xdf\xa3")
            and b"webm" in header[:4096]
        )
        if not valid:
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
    async with session.begin():
        video = await session.scalar(
            select(AccountVideo).where(AccountVideo.id == video_id).with_for_update()
        )
        if not video or video.owner_id != user.id:
            raise HTTPException(404, "Видео не найдено")
        if not video.ready:
            client, bucket = storage()
            video.object_key = await run_in_threadpool(
                verify_and_freeze, client, bucket, video
            )
            video.ready = True
    return {"id": video.id, "ready": video.ready}


@router.get("/account-videos/{video_id}/play")
async def play_video(
    video_id: uuid.UUID,
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    video = await session.get(AccountVideo, video_id)
    listing = await session.scalar(
        select(Listing)
        .where(
            Listing.video_asset_id == video_id,
            Listing.deleted_at.is_(None),
            Listing.status.in_(("active", "reserved", "sold")),
        )
        .limit(1)
    )
    if (
        not video
        or not video.ready
        or (video.owner_id != user.id and not listing and user.role != "admin")
    ):
        raise HTTPException(404, "Видео недоступно")
    client, bucket = storage()
    url = await run_in_threadpool(
        client.generate_presigned_url,
        "get_object",
        Params={"Bucket": bucket, "Key": video.object_key},
        ExpiresIn=300,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return {"url": url}
