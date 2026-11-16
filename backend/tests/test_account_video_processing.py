"""Real FFmpeg/ffprobe verification. Generated clips, isolated DB/files only."""

import json
import os
import shutil
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from app import account_video_processing as processing
from app.config import Settings
from app.models import AccountVideo
from app.account_video_volume import object_path
from test_account_video_volume import (
    video_app as video_app,
    account_db as account_db,
    configuration as configuration,
    upload,
)


def binaries():
    ffmpeg = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    ffprobe = os.environ.get("FFPROBE_BINARY") or shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("Real transcoding requires full FFmpeg/ffprobe (dedicated CI step)")
    return ffmpeg, ffprobe


@pytest.fixture
def codec_settings(monkeypatch):
    ffmpeg, ffprobe = binaries()
    settings = Settings(bot_token="", ffmpeg_binary=ffmpeg, ffprobe_binary=ffprobe)
    monkeypatch.setattr(processing, "get_settings", lambda: settings)
    return settings


def generate(
    path, *, seconds=3, width=1280, height=720, audio=False, fps=10, source_crf=14
):
    ffmpeg, _ = binaries()
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={width}x{height}:rate={fps}",
    ]
    if audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100"]
    command += [
        "-t",
        str(seconds),
        "-c:v",
        "libx264",
        "-threads",
        "1",
        "-preset",
        "ultrafast",
        "-crf",
        str(source_crf),
        "-pix_fmt",
        "yuv420p",
    ]
    if audio:
        command += ["-c:a", "aac", "-b:a", "96k"]
    else:
        command += ["-an"]
    command += ["-y", str(path)]
    result = subprocess.run(command, capture_output=True, timeout=180)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return path


def atoms(path):
    """Read only top-level atom headers, not incidental strings inside mdat."""
    result = []
    with path.open("rb") as handle:
        total = path.stat().st_size
        while handle.tell() + 8 <= total:
            header = handle.read(8)
            size = int.from_bytes(header[:4], "big")
            name = header[4:8].decode("ascii", "replace")
            overhead = 8
            if size == 1:
                size = int.from_bytes(handle.read(8), "big")
                overhead = 16
            if size == 0:
                size = total - handle.tell() + overhead
            assert size >= overhead
            result.append(name)
            handle.seek(size - overhead, 1)
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "width,height,suffix", [(1280, 720, ".mp4"), (720, 1280, ".mov")]
)
async def test_real_480p_h264_orientation_audio_and_faststart(
    codec_settings, tmp_path, width, height, suffix
):
    source = generate(
        tmp_path / ("source" + suffix), width=width, height=height, audio=True
    )
    target = tmp_path / "processed.mp4"
    events = []

    async def report(progress):
        events.append(progress)

    result = await processing.optimize(source, target, report)
    assert result["mode"] == "480p"
    assert result["codec"] == "h264" and result["pixel_format"] == "yuv420p"
    assert result["audio"] == ["aac"]
    limits = (854, 480) if width > height else (480, 854)
    assert result["width"] <= limits[0] and result["height"] <= limits[1]
    assert abs(result["width"] / result["height"] - width / height) < 0.01
    assert result["width"] % 2 == result["height"] % 2 == 0
    assert abs(result["duration"] - 3) < 0.15
    assert events == sorted(events) and events
    order = atoms(target)
    assert order.index("moov") < order.index("mdat")
    assert source.is_file(), "Optimization must not delete a user asset"


@pytest.mark.asyncio
async def test_already_small_compatible_video_is_remuxed_without_upscaling(
    codec_settings, tmp_path
):
    source = generate(tmp_path / "small.mp4", seconds=2, width=320, height=180, fps=5)
    result = await processing.optimize(source, tmp_path / "remux.mp4")
    assert result["mode"] == "remux"
    assert (result["width"], result["height"]) == (320, 180)
    assert atoms(tmp_path / "remux.mp4").index("moov") < atoms(
        tmp_path / "remux.mp4"
    ).index("mdat")


@pytest.mark.asyncio
async def test_corrupt_file_and_duration_limit_fail_without_output(
    codec_settings, tmp_path
):
    damaged = tmp_path / "bad.mp4"
    damaged.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"not a valid video")
    with pytest.raises(ValueError):
        await processing.optimize(damaged, tmp_path / "bad-output.mp4")
    assert not (tmp_path / "bad-output.mp4").exists()
    source = generate(tmp_path / "too-long.mp4", seconds=2, width=320, height=180)
    codec_settings.account_video_max_duration_seconds = 1
    with pytest.raises(ValueError):
        await processing.optimize(source, tmp_path / "too-long-output.mp4")
    assert not (tmp_path / "too-long-output.mp4").exists()


@pytest.mark.asyncio
async def test_volume_upload_queue_process_and_range_without_publishing(
    request, tmp_path, monkeypatch
):
    app, db, settings, ids = request.getfixturevalue("video_app")
    settings.ffmpeg_binary, settings.ffprobe_binary = binaries()
    settings.account_video_processing_enabled = True
    monkeypatch.setattr(processing, "get_settings", lambda: settings)
    source = generate(tmp_path / "source.mov", width=720, height=1280, audio=True)
    content = source.read_bytes()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        item, response = await upload(client, content, "video/quicktime")
        assert response.status_code == 200, response.text
        assert (
            response.json()["ready"] is False and response.json()["status"] == "queued"
        )
        complete = await client.post(f"/api/account-videos/{item['id']}/complete")
        assert complete.status_code == 200 and complete.json()["status"] == "queued"
        assert (
            await client.get(f"/api/account-videos/{item['id']}/play")
        ).status_code == 404

        @asynccontextmanager
        async def sessions():
            try:
                yield db
            finally:
                await db.rollback()

        assert await processing.process_one(sessions)
        assert not await processing.process_one(sessions), (
            "Ready assets cannot be encoded twice"
        )
        status = await client.get(f"/api/account-videos/{item['id']}/status")
        assert status.status_code == 200 and status.json()["ready"] is True
        assert status.json()["progress"] == 100
        current = await db.get(AccountVideo, uuid.UUID(item["id"]))
        key = current.processed_key
        await db.rollback()
        expected = object_path(key).read_bytes()
        assert atoms(object_path(key)).index("moov") < atoms(object_path(key)).index(
            "mdat"
        )
        play = await client.get(f"/api/account-videos/{item['id']}/play")
        assert play.status_code == 200
        chunk = await client.get(play.json()["url"], headers={"Range": "bytes=10-100"})
        assert chunk.status_code == 206 and chunk.content == expected[10:101]
        assert chunk.headers["content-type"] == "video/mp4"
        replay = await client.put(
            "/api" + item["upload_url"],
            content=content,
            headers={"Content-Type": "video/quicktime"},
        )
        assert replay.status_code == 200 and replay.json()["ready"]
        assert not await processing.process_one(sessions)
        app.state.viewer = ids[2]
        assert (
            await client.get(f"/api/account-videos/{item['id']}/status")
        ).status_code == 404


@pytest.mark.asyncio
async def test_cancelled_queued_video_is_not_processed_or_public(
    request, tmp_path, monkeypatch
):
    app, db, settings, _ = request.getfixturevalue("video_app")
    settings.ffmpeg_binary, settings.ffprobe_binary = binaries()
    settings.account_video_processing_enabled = True
    monkeypatch.setattr(processing, "get_settings", lambda: settings)
    source = generate(tmp_path / "cancel.mp4", width=320, height=180)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        item, result = await upload(client, source.read_bytes())
        assert result.status_code == 200
        cancel = await client.post(f"/api/account-videos/{item['id']}/cancel")
        assert cancel.status_code == 200 and cancel.json()["status"] == "cancelled"

        @asynccontextmanager
        async def sessions():
            try:
                yield db
            finally:
                await db.rollback()

        assert not await processing.process_one(sessions)
        assert (
            await client.get(f"/api/account-videos/{item['id']}/play")
        ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_ACCOUNT_VIDEO_BENCHMARK") != "1",
    reason="Explicit synthetic benchmark, not a mobile throughput claim",
)
@pytest.mark.parametrize(
    "seconds,width,height,suffix",
    [
        (30, 1280, 720, ".mp4"),
        (60, 720, 1280, ".mov"),
        (120, 1280, 720, ".mp4"),
        (180, 720, 1280, ".mov"),
    ],
)
async def test_measured_synthetic_video_benchmark(
    codec_settings, tmp_path, seconds, width, height, suffix, request, monkeypatch
):
    source = generate(
        tmp_path / ("benchmark" + suffix),
        seconds=seconds,
        width=width,
        height=height,
        fps=10,
        source_crf=18,
    )
    target = tmp_path / "result.mp4"
    result = await processing.optimize(source, target)
    assert result["width"] <= (854 if width > height else 480)
    assert result["height"] <= (480 if width > height else 854)
    # The actual raw-body transport is deliberately unchanged by server-side
    # encoding. Measure it twice on identical bytes, storage and ASGI HTTP
    # transport; these are local integration timings, NOT mobile network speed.
    app, _, settings, _ = request.getfixturevalue("video_app")
    settings.ffmpeg_binary, settings.ffprobe_binary = binaries()
    monkeypatch.setattr(processing, "get_settings", lambda: settings)
    content = source.read_bytes()
    mime = "video/quicktime" if suffix == ".mov" else "video/mp4"
    upload_times = {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        for name, enabled in (
            ("legacy_upload_http_seconds", False),
            ("queued_upload_http_seconds", True),
        ):
            settings.account_video_processing_enabled = enabled
            started = time.perf_counter()
            _, response = await upload(client, content, mime)
            upload_times[name] = round(time.perf_counter() - started, 4)
            assert response.status_code == 200, response.text
    values = {
        "fixture": "synthetic testsrc2, 10fps source; NOT phone/game footage",
        "seconds": seconds,
        "orientation": "landscape" if width > height else "portrait",
        "source_suffix": suffix,
        **result,
        **upload_times,
        "upload_test_condition": "Same generated source bytes; in-process ASGI HTTP + temporary local volume. No network throttling, no client compression.",
    }
    evidence = (
        Path(__file__).resolve().parents[2]
        / "webapp/tests/evidence/account-video-processing"
    )
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f"benchmark-{seconds}.json").write_text(
        json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("VIDEO_BENCHMARK " + json.dumps(values))
