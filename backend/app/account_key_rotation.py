"""Explicit maintenance command: keep old keys until no rows reference them.

python -m app.account_key_rotation       # dry run: counts only
python -m app.account_key_rotation --apply
Never run automatically during deployment. No secret is printed.
"""

import argparse
import asyncio

from sqlalchemy import func, select

from .account_crypto import keyring, seal, unseal
from .database import SessionLocal
from .models import AccountGrant, AccountSecret


async def rotate(sessions=SessionLocal, apply=False):
    _, active = keyring()
    changed = 0
    for model, field, prefix in (
        (AccountSecret, "listing_id", "listing"),
        (AccountGrant, "deal_id", "deal"),
    ):
        if not apply:
            async with sessions() as session:
                changed += int(
                    await session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.ciphertext.is_not(None), model.key_id != active)
                    )
                    or 0
                )
            continue
        while True:
            async with sessions() as session, session.begin():
                rows = (
                    await session.scalars(
                        select(model)
                        .where(model.ciphertext.is_not(None), model.key_id != active)
                        .order_by(getattr(model, field))
                        .limit(100)
                        .with_for_update()
                    )
                ).all()
                if not rows:
                    break
                for row in rows:
                    context = f"{prefix}:{getattr(row, field)}"
                    values = unseal(context, row.key_id, row.ciphertext)
                    row.key_id, row.ciphertext = seal(context, values)
                    values.clear()
                    changed += 1
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Rotate encrypted account envelopes; no values are logged"
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        count = asyncio.run(rotate(apply=args.apply))
    except Exception:
        raise SystemExit(
            "Rotation stopped. Keep all keys and investigate; plaintext omitted."
        ) from None
    print(f"{'Re-encrypted' if args.apply else 'Would re-encrypt'}: {count}")
