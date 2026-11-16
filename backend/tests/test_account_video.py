"""Video storage contract. In-memory provider only; no external traffic/keys."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import account_video


class StorageFixture:
    def __init__(self, data):
        self.data, self.copies = data, []

    def head_object(self, **_):
        return {"ContentLength": len(self.data), "ETag": "source-version"}

    def get_object(self, **kwargs):
        assert kwargs["IfMatch"] == "source-version"
        assert kwargs["Range"] == "bytes=0-65535"
        return {"Body": BytesIO(self.data)}

    def copy_object(self, **kwargs):
        self.copies.append(kwargs)


@pytest.mark.parametrize(
    "mime,data",
    [
        ("video/mp4", b"\x00\x00\x00\x18ftypisom" + b"0" * 32),
        ("video/webm", b"\x1aE\xdf\xa3" + b"test webm container"),
    ],
)
def test_valid_container_copied_to_an_immutable_new_key(mime, data):
    client = StorageFixture(data)
    video = SimpleNamespace(
        id="isolated-video",
        object_key="account-uploads/source",
        size_bytes=len(data),
        content_type=mime,
    )
    target = account_video.verify_and_freeze(client, "isolated-bucket", video)
    assert target.startswith("account-videos/isolated-video/")
    assert target != video.object_key
    assert client.copies[0]["CopySourceIfMatch"] == "source-version"
    assert client.copies[0]["ContentType"] == mime


@pytest.mark.parametrize(
    "data",
    [
        b"not a video",
        b"\x00\x00\x00\x18ftypavif" + b"0" * 20,
        b"\x00\x00\x00\x18ftypheic" + b"0" * 20,
    ],
)
def test_non_video_or_disguised_photo_is_not_published(data):
    client = StorageFixture(data)
    video = SimpleNamespace(
        id="isolated-video",
        object_key="account-uploads/source",
        size_bytes=len(data),
        content_type="video/mp4",
    )
    with pytest.raises(HTTPException) as error:
        account_video.verify_and_freeze(client, "isolated-bucket", video)
    assert error.value.status_code == 422 and not client.copies


def test_incomplete_upload_is_not_published():
    client = StorageFixture(b"\x00\x00\x00\x18ftypisom")
    video = SimpleNamespace(
        id="isolated-video",
        object_key="account-uploads/source",
        size_bytes=100,
        content_type="video/mp4",
    )
    with pytest.raises(HTTPException):
        account_video.verify_and_freeze(client, "isolated-bucket", video)
    assert not client.copies


def test_provider_error_never_exposes_a_signed_url_or_provider_secret():
    class FailedStorage:
        def head_object(self, **_):
            raise RuntimeError(
                "private-provider-token at https://private.example/signed"
            )

    video = SimpleNamespace(
        id="isolated-video",
        object_key="account-uploads/source",
        size_bytes=100,
        content_type="video/mp4",
    )
    with pytest.raises(HTTPException) as error:
        account_video.verify_and_freeze(FailedStorage(), "isolated-bucket", video)
    assert "private-provider" not in str(error.value.detail)
    assert "https://" not in str(error.value.detail)
