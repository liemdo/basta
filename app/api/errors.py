"""Map domain failures to HTTP responses. Unexpected errors stay out of the body."""

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app.exceptions import BrokerPublishError, CreditNotFound, IdempotencyConflict, UserNotFound

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CreditNotFound)
    def credit_not_found(_request: Request, _exc: CreditNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Credit not found"})

    @app.exception_handler(UserNotFound)
    def user_not_found(_request: Request, _exc: UserNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "User not found"})

    @app.exception_handler(IdempotencyConflict)
    def idempotency_conflict(_request: Request, _exc: IdempotencyConflict) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "Idempotency key already used for a different credit"},
        )

    @app.exception_handler(BrokerPublishError)
    def broker_publish_error(_request: Request, _exc: BrokerPublishError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Credit could not be queued"})

    @app.exception_handler(PyMongoError)
    def mongo_error(request: Request, _exc: PyMongoError) -> JSONResponse:
        logger.exception("MongoDB error path=%s", request.url.path)
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

    @app.exception_handler(RedisError)
    def redis_error(request: Request, _exc: RedisError) -> JSONResponse:
        logger.exception("Redis error path=%s", request.url.path)
        return JSONResponse(status_code=503, content={"detail": "Queue unavailable"})

    @app.exception_handler(ValidationError)
    def validation_error(request: Request, exc: ValidationError) -> JSONResponse:
        logger.info("validation failed path=%s", request.url.path)
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})

    @app.exception_handler(NotImplementedError)
    def not_implemented(request: Request, _exc: NotImplementedError) -> JSONResponse:
        logger.info("not implemented path=%s", request.url.path)
        return JSONResponse(status_code=501, content={"detail": "Not implemented"})

    @app.exception_handler(Exception)
    def unhandled(request: Request, _exc: Exception) -> JSONResponse:
        logger.exception("unhandled error path=%s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
