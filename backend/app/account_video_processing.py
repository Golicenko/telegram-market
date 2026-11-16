"""One bounded FFmpeg job at a time; DB owns the durable queue, not HTTP tasks."""

import asyncio
import hashlib
import json
import math
import logging
import shutil
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from .config import get_settings
from .database import SessionLocal
from .models import AccountVideo
from .account_video_volume import object_path, volume_root

logger = logging.getLogger("autoflow.video")


def tools_ready():
    settings = get_settings()
    return bool(
        shutil.which(settings.ffmpeg_binary) and shutil.which(settings.ffprobe_binary)
    )


async def probe(path):
    process = await asyncio.create_subprocess_exec(
        get_settings().ffprobe_binary,
        "-v",
        "error",
        "-max_alloc",
        "67108864",
        "-protocol_whitelist",
        "file,pipe",
        "-show_entries",
        "stream=codec_name,codec_type,width,height,pix_fmt:stream_side_data=rotation:format=duration,bit_rate,format_name",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 20)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode or len(output) > 1024 * 1024:
        raise ValueError("Невозможно прочитать видео")
    data = json.loads(output)
    stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), None
    )
    if not stream:
        raise ValueError("В файле нет видеодорожки")
    duration = float(data.get("format", {}).get("duration", 0))
    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
    if (
        not math.isfinite(duration)
        or duration <= 0
        or duration > get_settings().account_video_max_duration_seconds
        or width < 2
        or height < 2
        or width * height > 33000000
    ):
        raise ValueError("Длительность или разрешение видео превышает лимит")
    rotation = next(
        (
            abs(int(s.get("rotation", 0))) % 180
            for s in stream.get("side_data_list", [])
            if s.get("rotation")
        ),
        0,
    )
    if rotation:
        width, height = height, width
    return {
        "width": width,
        "height": height,
        "duration": duration,
        "codec": stream.get("codec_name"),
        "pixel_format": stream.get("pix_fmt"),
        "audio": [
            s.get("codec_name")
            for s in data.get("streams", [])
            if s.get("codec_type") == "audio"
        ],
        "bit_rate": int(data.get("format", {}).get("bit_rate", 0)),
    }


async def optimize(source, target, report=None):
    info = await probe(source)
    bounds = (854, 480) if info["width"] >= info["height"] else (480, 854)
    limits = (
        min(bounds[0], info["width"] // 2 * 2),
        min(bounds[1], info["height"] // 2 * 2),
    )
    compatible = (
        info["codec"] == "h264"
        and info["pixel_format"] == "yuv420p"
        and info["width"] <= limits[0]
        and info["height"] <= limits[1]
        and info["bit_rate"] <= 1800000
        and all(c == "aac" for c in info["audio"])
    )
    began = time.monotonic()
    command = [
        get_settings().ffmpeg_binary,
        "-nostdin",
        "-v",
        "error",
        "-max_alloc",
        "67108864",
        "-protocol_whitelist",
        "file,pipe",
        "-threads",
        "1",
        "-filter_threads",
        "1",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
    ]
    if compatible:
        command += ["-c", "copy"]
    else:
        command += [
            "-vf",
            f"scale={limits[0]}:{limits[1]}:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-maxrate",
            "1400k",
            "-bufsize",
            "2800k",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
        ]
    command += [
        "-movflags",
        "+faststart",
        "-map_metadata",
        "-1",
        "-progress",
        "pipe:1",
        "-y",
        str(target),
    ]
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        async with asyncio.timeout(600):
            previous = -1
            async for line in process.stdout:
                if line.startswith(b"out_time_us="):
                    try:
                        value = min(
                            99,
                            int(int(line.split(b"=")[1]) / (info["duration"] * 10000)),
                        )
                    except ValueError:
                        continue
                    if report and value // 10 > previous:
                        previous = value // 10
                        await report(value)
            await process.wait()
        if process.returncode or not target.is_file():
            raise ValueError("Не удалось подготовить видео")
        output = await probe(target)
        return {
            **output,
            "input_bytes": source.stat().st_size,
            "output_bytes": target.stat().st_size,
            "processing_seconds": round(time.monotonic() - began, 3),
            "mode": "remux" if compatible else "480p",
        }
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def process_one(sessions=None):
    sessions = sessions or SessionLocal
    if not tools_ready():
        return False
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        # Encoding is bounded to 10 min; each S3 transfer to 2 min. Recover only
        # after the full I/O + processing envelope, not during a live claim.
        rows = list(
            await session.scalars(
                select(AccountVideo)
                .where(AccountVideo.processing_status == "processing")
                .with_for_update(skip_locked=True)
            )
        )
        for row in rows:
            stamp = (row.processing_meta or {}).get("started_at", "")
            if stamp < (now - timedelta(minutes=20)).isoformat():
                row.processing_status = "queued"
        video = await session.scalar(
            select(AccountVideo)
            .where(
                AccountVideo.processing_status == "queued",
                AccountVideo.ready.is_(False),
            )
            .order_by(AccountVideo.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if not video:
            return False
        video_id, source_key = video.id, video.object_key
        claim = uuid.uuid4().hex
        meta = dict(video.processing_meta or {})
        if meta.get("attempts", 0) >= 3:
            video.processing_status = "failed"
            video.processing_meta = {
                **meta,
                "error": "Обработка прервана. Повторите загрузку.",
            }
            return True
        video.processing_status = "processing"
        video.processing_meta = {
            **meta,
            "started_at": now.isoformat(),
            "attempts": meta.get("attempts", 0) + 1,
            "progress": 0,
            "claim": claim,
        }

    async def report(value):
        async with sessions() as session, session.begin():
            row = await session.scalar(
                select(AccountVideo)
                .where(AccountVideo.id == video_id)
                .with_for_update()
            )
            if (
                row
                and row.processing_status == "processing"
                and row.processing_meta.get("claim") == claim
            ):
                row.processing_meta = {**row.processing_meta, "progress": value}
            else:
                raise ValueError("Обработка отменена")

    temporary = None
    try:
        # Local work files never live under the public static mount.
        with tempfile.TemporaryDirectory(prefix="autoflow-video-") as directory:
            directory = Path(directory)
            if source_key.startswith("volume:"):
                source = object_path(source_key)
            else:
                from .account_video import storage

                client, bucket = storage()
                source = directory / "input"
                from boto3.s3.transfer import TransferConfig

                transfer_config = TransferConfig(
                    max_concurrency=1, use_threads=False, num_download_attempts=2
                )
                await asyncio.wait_for(
                    run_in_threadpool(
                        client.download_file,
                        bucket,
                        source_key,
                        str(source),
                        Config=transfer_config,
                    ),
                    120,
                )
            target = directory / "output.mp4"
            result = await optimize(source, target, report)

            def file_hash():
                with target.open("rb") as handle:
                    return hashlib.file_digest(handle, "sha256").hexdigest()

            digest = await run_in_threadpool(file_hash)
            if source_key.startswith("volume:"):
                # Claim-owned key: an abandoned attempt cannot delete another
                # attempt's completed output, even when the bytes are identical.
                output_digest = hashlib.sha256(f"{digest}:{claim}".encode()).hexdigest()
                key = f"volume:videos/{video_id.hex}/{output_digest}"
            else:
                key = f"account-videos/{video_id}/{uuid.uuid4()}"
            async with sessions() as session, session.begin():
                row = await session.scalar(
                    select(AccountVideo)
                    .where(AccountVideo.id == video_id)
                    .with_for_update()
                )
                if (
                    not row
                    or row.processing_status != "processing"
                    or row.processing_meta.get("claim") != claim
                ):
                    return True
                # Record BEFORE storage I/O. Cancellation, restart or a failed
                # final DB commit cannot turn a completed file into an orphan.
                row.processing_meta = {
                    **row.processing_meta,
                    "output_keys": list(
                        dict.fromkeys(
                            [*row.processing_meta.get("output_keys", []), key]
                        )
                    ),
                }
            if source_key.startswith("volume:"):
                final = object_path(key)
                final.parent.mkdir(parents=True, exist_ok=True)
                # Copy on the mounted filesystem first, then atomic rename.
                temporary = final.with_name(final.name + f"-{claim}.part")
                await run_in_threadpool(shutil.copyfile, target, temporary)
                temporary.replace(final)
            else:
                await asyncio.wait_for(
                    run_in_threadpool(
                        client.upload_file,
                        str(target),
                        bucket,
                        key,
                        ExtraArgs={"ContentType": "video/mp4"},
                        Config=transfer_config,
                    ),
                    120,
                )
            async with sessions() as session, session.begin():
                row = await session.scalar(
                    select(AccountVideo)
                    .where(AccountVideo.id == video_id)
                    .with_for_update()
                )
                if (
                    not row
                    or row.processing_status != "processing"
                    or row.processing_meta.get("claim") != claim
                ):
                    return True
                row.processed_key, row.ready, row.processing_status = key, True, "ready"
                row.processing_meta = {**row.processing_meta, **result, "progress": 100}
            logger.info(
                "account_video_processed id=%s mode=%s input_bytes=%s output_bytes=%s seconds=%s",
                video_id,
                result["mode"],
                result["input_bytes"],
                result["output_bytes"],
                result["processing_seconds"],
            )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        async with sessions() as session, session.begin():
            row = await session.scalar(
                select(AccountVideo)
                .where(AccountVideo.id == video_id)
                .with_for_update()
            )
            if (
                row
                and row.processing_status == "processing"
                and row.processing_meta.get("claim") == claim
            ):
                row.processing_status = "failed"
                row.processing_meta = {
                    **row.processing_meta,
                    "error": "Не удалось обработать видео. Проверьте MP4/MOV и длительность или выберите другой файл.",
                }
        logger.warning(
            "account_video_processing_failed id=%s type=%s",
            video_id,
            type(error).__name__,
        )
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


async def run_worker():
    last_cleanup = 0
    while True:
        try:
            if time.monotonic() - last_cleanup > 3600:
                await cleanup_once()
                last_cleanup = time.monotonic()
            worked = await process_one()
        except asyncio.CancelledError:
            raise
        except Exception:
            worked = False
            logger.warning("account_video_worker_unavailable")
        await asyncio.sleep(1 if worked else 3)


async def cleanup_once(sessions=None):
    """New pipeline only: expire abandoned uploads, prune temporary originals.

    All listing references (including sold/deleted) protect the playback object.
    Legacy videos have NULL status and are never included.
    """
    from .models import Listing

    sessions = sessions or SessionLocal
    cutoff = datetime.now(UTC) - timedelta(days=7)
    async with sessions() as session, session.begin():
        rows = list(
            await session.scalars(
                select(AccountVideo)
                .where(
                    AccountVideo.processing_status.in_(
                        (
                            "uploading",
                            "queued",
                            "failed",
                            "cancelled",
                            "ready",
                            "pruning",
                            "expiring",
                        )
                    ),
                    AccountVideo.created_at < cutoff,
                )
                .order_by(AccountVideo.created_at)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        )
        jobs = []
        for video in rows:
            meta = dict(video.processing_meta or {})
            if video.processing_status in {"pruning", "expiring"}:
                jobs.append(
                    (
                        video.id,
                        meta.get("cleanup_keys", []),
                        meta.get("cleanup_linked", False),
                    )
                )
                continue
            linked = await session.scalar(
                select(Listing.id).where(Listing.video_asset_id == video.id).limit(1)
            )
            keys = list(
                dict.fromkeys(
                    filter(
                        None,
                        [
                            video.object_key,
                            meta.get("upload_key"),
                            *meta.get("output_keys", []),
                            video.processed_key,
                        ],
                    )
                )
            )
            if linked:
                if not video.processed_key:
                    continue
                keys = [key for key in keys if key != video.processed_key]
                video.processing_status = "pruning"
            else:
                video.ready, video.processing_status = False, "expiring"
            video.processing_meta = {
                **meta,
                "cleanup_keys": keys,
                "cleanup_linked": bool(linked),
            }
            jobs.append((video.id, keys, bool(linked)))
    for video_id, keys, linked in jobs:
        try:
            for key in keys:
                if key.startswith("volume:videos/"):
                    object_path(key).unlink(missing_ok=True)
                elif key.startswith(("account-uploads/", "account-videos/")):
                    from .account_video import storage

                    client, bucket = storage()
                    await asyncio.wait_for(
                        run_in_threadpool(client.delete_object, Bucket=bucket, Key=key),
                        30,
                    )
            async with sessions() as session, session.begin():
                row = await session.scalar(
                    select(AccountVideo)
                    .where(AccountVideo.id == video_id)
                    .with_for_update()
                )
                if row and row.processing_status == (
                    "pruning" if linked else "expiring"
                ):
                    row.processing_status = "ready_pruned" if linked else "expired"
                    row.processing_meta = {
                        k: v
                        for k, v in (row.processing_meta or {}).items()
                        if k not in {"cleanup_keys", "cleanup_linked"}
                    }
        except Exception:
            logger.warning("account_video_cleanup_retry id=%s", video_id)
    try:
        root = volume_root()
    except Exception:
        return
    if root.is_dir():
        for path in list(root.rglob("*.part"))[:200]:
            if (
                not path.is_symlink()
                and path.resolve().is_relative_to(root)
                and path.stat().st_mtime < time.time() - 3600
            ):
                path.unlink(missing_ok=True)
