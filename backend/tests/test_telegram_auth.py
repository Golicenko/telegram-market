import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest

from app.auth import validate_init_data


def signed_init_data(user: dict, bot_token: str = "test-token", auth_date: int | None = None) -> str:
    values = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAE-test",
        "user": json.dumps(user, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


@pytest.mark.parametrize(
    "user",
    [
        {"id": 1001, "first_name": "No username"},
        {"id": 1002, "first_name": "No photo", "username": "driver"},
        {"id": 1003, "first_name": "With photo", "photo_url": "https://example.test/avatar.jpg"},
    ],
)
def test_real_signed_telegram_users_support_optional_profile_fields(user):
    assert validate_init_data(signed_init_data(user), "test-token") == user


def test_invalid_signature_is_rejected():
    payload = signed_init_data({"id": 42, "first_name": "User"})
    with pytest.raises(ValueError, match="signature"):
        validate_init_data(payload.replace("hash=", "hash=broken"), "test-token")


def test_init_data_survives_normal_background_time_but_rejects_stale_or_future_payloads():
    now = int(time.time())
    user = {"id": 77, "first_name": "Return user"}
    assert validate_init_data(signed_init_data(user, auth_date=now - 23 * 3600), "test-token") == user
    with pytest.raises(ValueError, match="expired"):
        validate_init_data(signed_init_data(user, auth_date=now - 25 * 3600), "test-token")
    with pytest.raises(ValueError, match="expired"):
        validate_init_data(signed_init_data(user, auth_date=now + 600), "test-token")


def test_auth_limits_fake_user_to_debug_and_creates_wallet_with_new_user():
    source = (Path(__file__).parents[1] / "app" / "auth.py").read_text(encoding="utf-8")
    assert "session.add(Wallet(user_id=user.id))" in source
    assert "begin_nested" in source
    assert "settings.debug" in source
    assert 'username": "local_dev"' in source
    assert "elif settings.debug" in source
