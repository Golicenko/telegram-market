from contextlib import asynccontextmanager
import asyncio
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .bot import configure_telegram_webhook
from .database import engine
from .routes import UPLOAD_DIR, recover_training_background_jobs, router


settings = get_settings()
WEBAPP_DIR = Path(__file__).resolve().parents[2] / "webapp"
logger = logging.getLogger("autoflow.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await configure_telegram_webhook()
    recovery_task = asyncio.create_task(recover_training_background_jobs())
    try:
        yield
    finally:
        if not recovery_task.done():
            recovery_task.cancel()
        await engine.dispose()


app = FastAPI(title="AUTOFLOW MARKET API", version="0.3.0", lifespan=lifespan)


@app.middleware("http")
async def diagnostic_request_log(request: Request, call_next):
    """Emit Railway-friendly diagnostics without initData, tokens or request bodies."""
    started_at = perf_counter()
    status_code = 500
    error_type = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        if status_code >= 400:
            error_type = "http"
        return response
    except Exception as exc:
        error_type = type(exc).__name__
        raise
    finally:
        if request.url.path.startswith("/api"):
            logger.info(
                "api_request %s",
                json.dumps(
                    {
                        "endpoint": request.url.path,
                        "status": status_code,
                        "duration_ms": round((perf_counter() - started_at) * 1000),
                        "error_type": error_type,
                        "telegram_user_id": getattr(request.state, "telegram_user_id", None),
                        "platform": request.headers.get("X-Telegram-Platform", "unknown")[:32],
                        "startup_stage": request.headers.get("X-AutoFlow-Startup-Stage", "unknown")[:48],
                        "time": datetime.now(UTC).isoformat(),
                    },
                    ensure_ascii=False,
                ),
            )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.include_router(router)
if WEBAPP_DIR.exists():
    app.mount("/", StaticFiles(directory=WEBAPP_DIR, html=True), name="webapp")
