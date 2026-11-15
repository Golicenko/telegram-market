"""Versioned authenticated envelopes. Plaintext never enters public ORM objects."""

import base64
import json
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException

from .config import get_settings


def keyring():
    settings = get_settings()
    try:
        keys = {
            name: base64.b64decode(value, validate=True)
            for name, value in settings.account_secret_keys.items()
        }
        if any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name) for name in keys):
            raise ValueError()
        if (
            not settings.account_secret_active_key
            or settings.account_secret_active_key not in keys
            or any(len(k) != 32 for k in keys.values())
        ):
            raise ValueError()
        return keys, settings.account_secret_active_key
    except (ValueError, TypeError):
        raise HTTPException(
            503, "Защищённая выдача ещё не настроена администратором"
        ) from None


def seal(context, values):
    keys, active = keyring()
    nonce = os.urandom(12)
    ciphertext = AESGCM(keys[active]).encrypt(
        nonce, json.dumps(values, ensure_ascii=False).encode(), str(context).encode()
    )
    return active, nonce + ciphertext


def unseal(context, key_id, ciphertext):
    keys, _ = keyring()
    try:
        if not ciphertext or len(ciphertext) < 29:
            raise ValueError()
        return json.loads(
            AESGCM(keys[key_id]).decrypt(
                ciphertext[:12], ciphertext[12:], str(context).encode()
            )
        )
    except (KeyError, ValueError, InvalidTag, UnicodeError, TypeError):
        raise HTTPException(
            503, "Данные временно недоступны. Обратитесь в поддержку по номеру сделки"
        ) from None
