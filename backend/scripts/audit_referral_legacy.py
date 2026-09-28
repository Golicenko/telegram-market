"""Read-only preflight for 0043. Run before deployment if 0042 issued rewards."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from app.database import engine  # noqa: E402


async def read_legacy_rewards(connection):
    # Mirror the migration guard, including inconsistent balances without a debit.
    return (
        (
            await connection.execute(
                text("""
                WITH rewards AS (
                    SELECT r.user_id, SUM(r.amount) reward_total,
                        MIN(t.created_at) first_reward
                    FROM referral_rewards r
                    JOIN wallet_transactions t ON t.id=r.transaction_id
                    GROUP BY r.user_id
                )
                SELECT r.*, w.earned_balance, w.earned_frozen_balance, w.total_earned,
                    (w.id IS NULL OR w.earned_balance < r.reward_total
                        OR w.total_earned < r.reward_total
                        OR EXISTS (
                            SELECT 1 FROM wallet_transactions x
                            WHERE x.user_id=r.user_id AND x.created_at >= r.first_reward
                              AND (x.available_after<x.available_before
                                   OR x.frozen_after!=x.frozen_before)
                        )) needs_review
                FROM rewards r LEFT JOIN wallets w ON w.user_id=r.user_id
                ORDER BY r.user_id
                """)
            )
        )
        .mappings()
        .all()
    )


async def main():
    try:
        async with engine.connect() as connection:
            rows = await read_legacy_rewards(connection)
            for row in rows:
                print(
                    dict(row)
                )  # Internal account UUID only; no Telegram identity or secrets.
            review_count = sum(bool(row["needs_review"]) for row in rows)
            print(
                f"Accounts with legacy rewards: {len(rows)}; "
                f"requiring review: {review_count}; no data changed."
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
