from pathlib import Path

import pytest
from pydantic import ValidationError

from app.routes import database_health, health
from app.schemas import ClientDiagnosticCreate


@pytest.mark.asyncio
async def test_lightweight_health_response_does_not_expose_configuration():
    assert await health() == {"status": "ok"}


def test_webhook_registration_cannot_block_application_startup():
    source = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    lifespan = source[source.index("async def lifespan"):source.index("app = FastAPI")]
    assert 'run_startup_job("telegram_webhook", configure_telegram_webhook)' in lifespan
    assert "await configure_telegram_webhook()" not in lifespan
    assert "await asyncio.gather(*recovery_tasks, return_exceptions=True)" in lifespan


def test_client_diagnostic_accepts_only_bounded_safe_metadata():
    payload = ClientDiagnosticCreate(
        error_id="AF-7K2P9",
        context="startup",
        endpoint="/api/me",
        status=503,
        error_type="http",
        user_agent="Telegram Android WebView",
    )
    assert payload.error_id == "AF-7K2P9"
    with pytest.raises(ValidationError):
        ClientDiagnosticCreate(
            error_id="AF-7K2P9",
            context="startup",
            bot_token="must-not-be-accepted",
        )


@pytest.mark.asyncio
async def test_database_health_returns_503_instead_of_leaking_connection_errors():
    class OfflineSession:
        async def execute(self, _query):
            raise ConnectionRefusedError("private database address")

    with pytest.raises(Exception) as error:
        await database_health(OfflineSession())
    assert getattr(error.value, "status_code", None) == 503
    assert getattr(error.value, "detail", None) == "database unavailable"
