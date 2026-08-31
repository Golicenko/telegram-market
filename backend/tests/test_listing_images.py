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


@pytest.mark.parametrize("image_format,mode", [("JPEG", "RGB"), ("PNG", "RGBA"), ("WEBP", "RGB"), ("HEIF", "RGB")])
def test_mobile_web_images_are_normalized_to_browser_safe_jpeg(image_format, mode):
    content, content_type, extension = normalize_image_content(make_image(image_format, mode=mode))
    assert content.startswith(b"\xff\xd8\xff")
    assert content_type == "image/jpeg"
    assert extension == ".jpg"


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
        return self.image if model is UploadedImage and self.image.id == image_id else None


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
    assert "await run_in_threadpool(normalize_image_content, content)" in source
