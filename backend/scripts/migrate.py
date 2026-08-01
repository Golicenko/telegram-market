"""Run Alembic migrations with Railway-friendly validation and retries."""

from __future__ import annotations

import os
import socket
import sys
import time
import traceback
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url


BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_DIR / "alembic.ini"
DEFAULT_ATTEMPTS = 12
DEFAULT_RETRY_SECONDS = 5


def _positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw_value!r}.") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be at least 1.")
    return value


def _validate_database_url() -> str:
    raw_url = os.getenv("DATABASE_URL", "").strip()
    if not raw_url:
        raise RuntimeError(
            "DATABASE_URL is missing in the application service. Set it to a Railway "
            "reference such as ${{Postgres.DATABASE_URL}}."
        )
    if raw_url.startswith("${{") or "DATABASE_URL}}" in raw_url:
        raise RuntimeError(
            "DATABASE_URL is still a literal Railway reference. Verify the exact "
            "PostgreSQL service name in ${{<service>.DATABASE_URL}}."
        )

    if raw_url.startswith("postgres://"):
        sqlalchemy_url = raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif raw_url.startswith("postgresql://"):
        sqlalchemy_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    else:
        sqlalchemy_url = raw_url

    parsed_url = make_url(sqlalchemy_url)
    if not parsed_url.drivername.startswith("postgresql"):
        raise RuntimeError("DATABASE_URL must point to PostgreSQL.")
    if not parsed_url.host or not parsed_url.database:
        raise RuntimeError("DATABASE_URL must contain a host and database name.")

    target = f"{parsed_url.host}:{parsed_url.port or 5432}/{parsed_url.database}"
    print(f"Migration target: {target}", flush=True)
    return target


def main() -> int:
    target = _validate_database_url()
    attempts = _positive_int("MIGRATION_MAX_ATTEMPTS", DEFAULT_ATTEMPTS)
    retry_seconds = _positive_int("MIGRATION_RETRY_SECONDS", DEFAULT_RETRY_SECONDS)
    alembic_config = Config(str(ALEMBIC_CONFIG))

    os.chdir(BACKEND_DIR)
    for attempt in range(1, attempts + 1):
        try:
            print(f"Running Alembic migration (attempt {attempt}/{attempts})...", flush=True)
            command.upgrade(alembic_config, "head")
            print("Alembic migrations completed successfully.", flush=True)
            return 0
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:  # Alembic can wrap driver errors in several exception types.
            if attempt == attempts:
                print(f"Migration failed for {target}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                traceback.print_exc()
                return 1
            print(
                f"PostgreSQL is not ready or migration failed: {type(exc).__name__}: {exc}. "
                f"Retrying in {retry_seconds}s...",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(retry_seconds)

    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, socket.gaierror) as exc:
        print(f"Migration configuration error: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2) from exc
