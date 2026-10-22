"""HTTP application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import credits, health, users
from app.api.errors import register_exception_handlers
from app.config import get_settings
from app.db import close_clients, get_database
from app.pages import router as pages_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        get_database(get_settings())
    except Exception:
        logger.exception("startup failed")
        raise
    yield
    close_clients()


def create_app() -> FastAPI:
    app = FastAPI(title="Async Credit Service", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(credits.router)
    app.include_router(users.router)
    app.include_router(pages_router)
    return app


app = create_app()
