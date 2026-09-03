from contextlib import asynccontextmanager
import asyncio
from datetime import UTC, datetime
import json
import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .bot import configure_telegram_webhook
from .broadcasts import recover_admin_broadcasts
from .database import engine
from .frontend import FRONTEND_BUILD, WEBAPP_DIR, versioned_webapp_url
from .routes import UPLOAD_DIR, recover_deal_purchase_notifications, recover_training_background_jobs, run_deal_transfer_reminder_worker, run_seller_response_timeout_worker, router


settings = get_settings()
logger = logging.getLogger("autoflow.api")


async def run_startup_job(name: str, job) -> None:
    """Keep optional recovery work observable without blocking HTTP startup."""
    try:
        await job()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("startup_job_failed name=%s error_type=%s", name, type(exc).__name__)


def set_frontend_cache_headers(request: Request, response) -> None:
    path = request.url.path
    if path == "/" or path.endswith("/index.html") or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif path.startswith(("/js/", "/css/")):
        requested_build = request.query_params.get("v")
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable"
            if requested_build and requested_build == FRONTEND_BUILD
            else "no-cache, must-revalidate"
        )
    if path == "/" or path.startswith(("/js/", "/css/")):
        response.headers["X-AutoFlow-Frontend-Build"] = FRONTEND_BUILD


@asynccontextmanager
async def lifespan(_app: FastAPI):
    recovery_tasks = [
        asyncio.create_task(run_startup_job("telegram_webhook", configure_telegram_webhook)),
        asyncio.create_task(run_startup_job("training_recovery", recover_training_background_jobs)),
        asyncio.create_task(run_startup_job("deal_notification_recovery", recover_deal_purchase_notifications)),
        asyncio.create_task(run_startup_job("deal_transfer_reminder_worker", run_deal_transfer_reminder_worker)),
        asyncio.create_task(run_startup_job("seller_response_timeout_worker", run_seller_response_timeout_worker)),
        asyncio.create_task(run_startup_job("broadcast_recovery", recover_admin_broadcasts)),
    ]
    try:
        yield
    finally:
        for recovery_task in recovery_tasks:
            if not recovery_task.done():
                recovery_task.cancel()
        await asyncio.gather(*recovery_tasks, return_exceptions=True)
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
        set_frontend_cache_headers(request, response)
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
                        "error_id": request.headers.get("X-AutoFlow-Error-ID", "")[:16] or None,
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


@app.get("/", include_in_schema=False)
async def frontend_entry(request: Request):
    """Turn BotFather's stable Main Mini App URL into a build-specific URL."""
    if request.query_params.get("af_build") != FRONTEND_BUILD:
        response = RedirectResponse(versioned_webapp_url(str(request.url)), status_code=307)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response
    return FileResponse(WEBAPP_DIR / "index.html", media_type="text/html")


if WEBAPP_DIR.exists():
    app.mount("/", StaticFiles(directory=WEBAPP_DIR, html=True), name="webapp")
