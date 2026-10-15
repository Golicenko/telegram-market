from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException, Request, UploadFile
from PIL import Image

from app.models import UploadedImage, User
from app.routes import normalize_image_content, upload_image, uploaded_image


def make_image(image_format: str, *, mode: str = "RGB") -> bytes:
    image = Image.new(mode, (32, 24), (255, 20, 10) if mode == "RGB" else (255, 20, 10, 128))
    output = BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def upload_request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/uploads", "headers": [(b"x-autoflow-error-id", b"AF-TEST01")]})


@pytest.mark.parametrize("image_format,mode", [("JPEG", "RGB"), ("PNG", "RGBA"), ("WEBP", "RGB"), ("HEIF", "RGB"), ("AVIF", "RGB"), ("GIF", "RGB"), ("BMP", "RGB"), ("TIFF", "RGB")])
def test_mobile_web_images_are_normalized_to_browser_safe_jpeg(image_format, mode):
    content, content_type, extension = normalize_image_content(make_image(image_format, mode=mode))
    assert content.startswith(b"\xff\xd8\xff")
    assert content_type == "image/jpeg"
    assert extension == ".jpg"


@pytest.mark.parametrize("image_format,mime,name", [("HEIF", "application/octet-stream", "phone.heic"), ("HEIF", "", "phone.heif"), ("AVIF", "image/jpeg", "edited.jpg"), ("PNG", "text/plain", "screenshot.bin")])
@pytest.mark.asyncio
async def test_contents_not_mime_or_extension_and_saved_media_is_readable(image_format, mime, name):
    session = FakeImageSession()
    upload = UploadFile(filename=name, file=BytesIO(make_image(image_format)), headers={"content-type": mime})
    await upload_image(upload_request(), upload, User(id=uuid.uuid4(), telegram_id=99), session)
    response = await uploaded_image(session.image.id, session)
    with Image.open(BytesIO(response.body)) as image:
        image.load()
        assert image.format == "JPEG" and image.size == (32, 24)


def test_exif_orientation_and_private_metadata_are_removed():
    original = Image.new("RGB", (80, 40), "red")
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "private author"
    output = BytesIO()
    original.save(output, "JPEG", exif=exif)
    content, _, _ = normalize_image_content(output.getvalue())
    with Image.open(BytesIO(content)) as image:
        assert image.size == (40, 80)
        assert not image.getexif()


def test_palette_transparency_becomes_white_not_black():
    original = Image.new("P", (20, 20), 0)
    output = BytesIO()
    original.save(output, "PNG", transparency=0)
    content, _, _ = normalize_image_content(output.getvalue())
    with Image.open(BytesIO(content)) as image:
        assert min(image.getpixel((10, 10))) > 245


def test_48mp_phone_jpeg_is_bounded_and_resized():
    image = Image.new("RGB", (8000, 6000), "blue")
    output = BytesIO()
    image.save(output, "JPEG")
    image.close()
    content, _, _ = normalize_image_content(output.getvalue())
    with Image.open(BytesIO(content)) as result:
        assert result.size == (2560, 1920)


@pytest.mark.parametrize("content", [b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', b'%PDF-1.7', b'<html>not a photo</html>', b'\xff\xd8\xffbroken', b''])
def test_non_raster_or_corrupt_files_are_never_served(content):
    with pytest.raises(HTTPException) as error:
        normalize_image_content(content)
    assert error.value.status_code in {415, 422}


def test_decoded_pixel_limit_is_checked_before_load(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(HTTPException) as error:
        normalize_image_content(make_image("PNG"))
    assert error.value.status_code == 413


def test_truncated_jpeg_has_actionable_decode_error():
    with pytest.raises(HTTPException) as error:
        normalize_image_content(make_image("JPEG")[:-30])
    assert error.value.status_code in {415, 422}


def test_fake_image_is_rejected_from_server_validation():
    with pytest.raises(HTTPException) as error:
        normalize_image_content(b"not-an-image")
    assert error.value.status_code == 415


class FakeImageSession:
    def __init__(self):
        self.image = None

    def add(self, image):
        image.id = image.id or uuid.uuid4()
        self.image = image

    async def commit(self):
        return None

    async def get(self, model, image_id):
        return self.image if model is UploadedImage and self.image and self.image.id == image_id else None


@pytest.mark.asyncio
async def test_upload_save_and_read_image_flow():
    session = FakeImageSession()
    user = User(id=uuid.uuid4(), telegram_id=100, first_name="Mobile", role="user")
    upload = UploadFile(filename="iphone.heic", file=BytesIO(make_image("HEIF")), headers={"content-type": "image/heic"})
    result = await upload_image(upload_request(), upload, user, session)
    assert result["url"] == f"/api/media/{session.image.id}"
    assert session.image.owner_id == user.id
    assert session.image.content_type == "image/jpeg"
    response = await uploaded_image(session.image.id, session)
    assert response.media_type == "image/jpeg"
    assert response.body.startswith(b"\xff\xd8\xff")


@pytest.mark.asyncio
async def test_oversized_upload_returns_413_before_image_processing(monkeypatch):
    monkeypatch.setattr("app.routes.get_settings", lambda: SimpleNamespace(upload_max_bytes=10))
    user = User(id=uuid.uuid4(), telegram_id=101, first_name="Mobile", role="user")
    upload = UploadFile(filename="large.jpg", file=BytesIO(b"x" * 11), headers={"content-type": "image/jpeg"})
    with pytest.raises(HTTPException) as error:
        await upload_image(upload_request(), upload, user, FakeImageSession())
    assert error.value.status_code == 413


def test_upload_normalization_runs_outside_the_async_event_loop():
    source = (Path(__file__).parents[1] / "app" / "routes.py").read_text(encoding="utf-8")
    assert "await run_in_threadpool(normalize_image_content, file.file)" in source


@pytest.mark.parametrize("megabytes", [20, 30, 50])
@pytest.mark.asyncio
async def test_large_real_raster_is_optimized_without_reading_full_upload(megabytes):
    # Uncompressed real BMP pixels, not a tiny image padded with fake bytes.
    side = int((megabytes * 1024 * 1024 / 3) ** .5) + 1
    source = Image.new("RGB", (side, side), "blue")
    content = BytesIO()
    source.save(content, "BMP")
    source.close()
    assert content.tell() >= megabytes * 1024 * 1024
    content.seek(0)
    upload = UploadFile(filename="camera.bin", file=content, headers={"content-type": "application/octet-stream"})
    async def no_full_read(*args):
        pytest.fail("Must decode spool directly, not duplicate 50 MB via UploadFile.read")
    upload.read = no_full_read
    session = FakeImageSession()
    await upload_image(upload_request(), upload, User(id=uuid.uuid4(), telegram_id=99), session)
    assert session.image.size_bytes <= 2 * 1024 * 1024
    assert content.closed
    with Image.open(BytesIO(session.image.data)) as result:
        assert max(result.size) <= 2560
        result.load()


@pytest.mark.asyncio
async def test_identical_retries_reuse_owner_scoped_image_and_thumbnail():
    user = User(id=uuid.uuid4(), telegram_id=99)
    session = FakeImageSession()
    results = []
    for _ in range(2):
        upload = UploadFile(filename="phone.png", file=BytesIO(make_image("PNG")))
        results.append(await upload_image(upload_request(), upload, user, session))
    assert results[0] == results[1]
    response = await uploaded_image(session.image.id, session, preview=True)
    with Image.open(BytesIO(response.body)) as image:
        assert max(image.size) <= 480
    other = FakeImageSession()
    upload = UploadFile(filename="phone.png", file=BytesIO(make_image("PNG")))
    assert await upload_image(upload_request(), upload, User(id=uuid.uuid4(), telegram_id=100), other) != results[0]


@pytest.mark.asyncio
async def test_rejected_upload_closes_temporary_spool():
    source = BytesIO(b"bad photo")
    with pytest.raises(HTTPException):
        await upload_image(upload_request(), UploadFile(filename="bad.jpg", file=source), User(id=uuid.uuid4(), telegram_id=99), FakeImageSession())
    assert source.closed
