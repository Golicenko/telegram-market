import tempfile
import struct

import pytest
from fastapi import HTTPException, UploadFile

from app import routes
from app.config import Settings


def upload_with_size(name: str, header: bytes, size: int) -> UploadFile:
    stream = tempfile.TemporaryFile()
    stream.write(header)
    if size > len(header):
        stream.seek(size - 1)
        stream.write(b"\0")
    stream.seek(0)
    return UploadFile(filename=name, file=stream)


@pytest.mark.parametrize(
    ("header", "expected_type", "expected_mime"),
    [
        (b"\xff\xd8\xff\xe0", "photo", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "photo", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBP", "photo", "image/webp"),
        (b"%PDF-1.7", "document", "application/pdf"),
        (b"PK\x03\x04", "document", "application/zip"),
        (b"\x1aE\xdf\xa3", "document", "video/webm"),
        (b"\x00\x00\x00\x18ftypqt  ", "document", "video/quicktime"),
        (b"\x00\x00\x00\x18ftypisom", "video", "video/mp4"),
        ("Текстовый материал".encode(), "document", "text/plain"),
    ],
)
def test_training_material_type_is_detected_from_content(header, expected_type, expected_mime):
    assert routes.detect_training_material(header) == (expected_type, expected_mime)


def test_unsupported_training_binary_has_clear_415_error():
    with pytest.raises(HTTPException) as error:
        routes.detect_training_material(b"\x00\x01\x02\x03unknown")
    assert error.value.status_code == 415
    assert error.value.detail["code"] == "unsupported_training_file"


@pytest.mark.asyncio
async def test_large_video_is_streamed_to_telegram_and_not_rejected_by_old_20mb_limit(monkeypatch):
    upload = upload_with_size("lesson.mp4", b"\x00\x00\x00\x18ftypisom", 25 * 1024 * 1024)
    captured = {}

    async def fake_upload(telegram_id, material_type, filename, content, content_type, file_size):
        captured.update(
            telegram_id=telegram_id,
            material_type=material_type,
            filename=filename,
            content=content,
            content_type=content_type,
            file_size=file_size,
        )
        return {"delivery_reference": "telegram-file-id", "material_type": material_type}

    monkeypatch.setattr(routes, "upload_bot_material", fake_upload)
    admin = type("Admin", (), {"telegram_id": 123})()
    result = await routes.upload_training_material(file=upload, admin=admin, settings=Settings())

    assert result["delivery_reference"] == "telegram-file-id"
    assert captured["content"] is upload.file
    assert captured["file_size"] == 25 * 1024 * 1024
    assert captured["material_type"] == "video"


@pytest.mark.asyncio
async def test_video_duration_over_ten_minutes_is_not_a_validation_limit(monkeypatch):
    # mvhd timescale=1 and duration=660 represents eleven minutes. Upload validation
    # deliberately checks transport size and format, never media duration.
    ftyp = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 12
    mvhd_payload = b"\x00\x00\x00\x00" + b"\x00" * 8 + struct.pack(">II", 1, 660)
    mvhd = struct.pack(">I", len(mvhd_payload) + 8) + b"mvhd" + mvhd_payload
    upload = upload_with_size("long-lesson.mp4", ftyp + mvhd, 1024 * 1024)
    captured = {}

    async def fake_upload(_telegram_id, material_type, _filename, _content, _content_type, file_size):
        captured.update(material_type=material_type, file_size=file_size)
        return {"delivery_reference": "long-video-file-id", "material_type": material_type}

    monkeypatch.setattr(routes, "upload_bot_material", fake_upload)
    admin = type("Admin", (), {"telegram_id": 123})()
    result = await routes.upload_training_material(file=upload, admin=admin, settings=Settings())

    assert result["delivery_reference"] == "long-video-file-id"
    assert captured == {"material_type": "video", "file_size": 1024 * 1024}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "header", "size", "expected_max_bytes", "expected_code"),
    [
        ("cover.jpg", b"\xff\xd8\xff\xe0", 10 * 1024 * 1024 + 1, 10 * 1024 * 1024, "training_file_too_large"),
        ("lesson.mp4", b"\x00\x00\x00\x18ftypisom", 50 * 1024 * 1024 + 1, 2 * 1024 * 1024 * 1024, "use_telegram_training_inbox"),
    ],
)
async def test_training_upload_enforces_real_telegram_transport_limits(name, header, size, expected_max_bytes, expected_code):
    upload = upload_with_size(name, header, size)
    admin = type("Admin", (), {"telegram_id": 123})()
    with pytest.raises(HTTPException) as error:
        await routes.upload_training_material(file=upload, admin=admin, settings=Settings())
    assert error.value.status_code == 413
    assert error.value.detail["max_bytes"] == expected_max_bytes
    assert error.value.detail["code"] == expected_code


def test_telegram_inbox_accepts_500mb_video_without_duration_limit():
    result = routes.extract_training_inbox_video(
        {
            "message_id": 77,
            "video": {
                "file_id": "telegram-file-id",
                "file_unique_id": "stable-id",
                "file_name": "lesson-75-minutes.mp4",
                "mime_type": "video/mp4",
                "file_size": 500 * 1024 * 1024,
                "duration": 75 * 60,
            },
        },
        2 * 1024 * 1024 * 1024,
    )
    assert result is not None
    assert result["file_size"] == 500 * 1024 * 1024
    assert result["duration_seconds"] == 75 * 60
    assert result["telegram_file_id"] == "telegram-file-id"


def test_telegram_inbox_accepts_mov_document_and_rejects_non_video_document():
    mov = routes.extract_training_inbox_video(
        {"document": {"file_id": "mov-id", "file_unique_id": "u", "file_name": "lesson.mov", "mime_type": "application/octet-stream", "file_size": 200_000_000}},
        2 * 1024 * 1024 * 1024,
    )
    pdf = routes.extract_training_inbox_video(
        {"document": {"file_id": "pdf-id", "file_name": "notes.pdf", "mime_type": "application/pdf", "file_size": 1000}},
        2 * 1024 * 1024 * 1024,
    )
    assert mov is not None and mov["material_type"] == "document"
    assert pdf is None


def test_telegram_inbox_enforces_two_gib_metadata_boundary_without_reading_file():
    message = {"video": {"file_id": "large-id", "file_unique_id": "large-u", "mime_type": "video/mp4", "file_size": 2 * 1024 * 1024 * 1024}}
    assert routes.extract_training_inbox_video(message, 2 * 1024 * 1024 * 1024) is not None
    message["video"]["file_size"] += 1
    assert routes.extract_training_inbox_video(message, 2 * 1024 * 1024 * 1024) is None
