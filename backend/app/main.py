from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .bot import configure_telegram_webhook
from .database import engine
from .routes import UPLOAD_DIR, router


settings = get_settings()
WEBAPP_DIR = Path(__file__).resolve().parents[2] / "webapp"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await configure_telegram_webhook()
    yield
    await engine.dispose()


app = FastAPI(title="AUTOFLOW MARKET API", version="0.3.0", lifespan=lifespan)
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
