from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, File, UploadFile

from app.upload_guard import ImageUploadGuard


def guarded_app():
    app = FastAPI()
    app.add_middleware(ImageUploadGuard)

    @app.post("/api/uploads")
    async def upload(file: UploadFile = File(...)):
        return {"size": file.size}

    @app.post("/other")
    async def other(file: UploadFile = File(...)):
        return {"size": file.size}
    return app


@pytest.mark.asyncio
async def test_body_limit_rejects_content_length_before_spooling(monkeypatch):
    monkeypatch.setattr("app.upload_guard.get_settings", lambda: SimpleNamespace(upload_max_bytes=1024))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=guarded_app()), base_url="http://test") as client:
        response = await client.post("/api/uploads", files={"file": ("photo.jpg", b"x" * 150000)})
        assert response.status_code == 413
        # No accidental change to unrelated training or other upload limits.
        assert (await client.post("/other", files={"file": ("file", b"x" * 150000)})).status_code == 200


@pytest.mark.asyncio
async def test_chunked_overflow_is_413_and_closes_parser_spools(monkeypatch):
    from starlette import formparsers
    original = formparsers.SpooledTemporaryFile
    opened = []
    def capture(*args, **kwargs):
        file = original(*args, **kwargs)
        opened.append(file)
        return file
    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", capture)
    monkeypatch.setattr("app.upload_guard.get_settings", lambda: SimpleNamespace(upload_max_bytes=1024))
    async def chunks():
        yield b'--test\r\nContent-Disposition: form-data; name="file"; filename="phone.jpg"\r\n\r\n'
        for _ in range(20):
            yield b"x" * 10000
        yield b"\r\n--test--\r\n"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=guarded_app()), base_url="http://test") as client:
        response = await client.post("/api/uploads", content=chunks(), headers={"Content-Type": "multipart/form-data; boundary=test"})
        assert response.status_code == 413, response.text
        assert opened and all(file.closed for file in opened)
        assert (await client.post("/api/uploads", files={"file": ("photo.jpg", b"small")})).status_code == 200
