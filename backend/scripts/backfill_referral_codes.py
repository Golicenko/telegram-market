"""Resumable code backfill, small commits; never grants referral relationships."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine  # noqa: E402
from app.referrals import backfill_referral_codes  # noqa: E402


async def main():
    try:
        total = await backfill_referral_codes()
        print(f"Assigned {total} codes. Safe to rerun.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
