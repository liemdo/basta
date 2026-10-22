"""Celery application. Status stays in MongoDB; the broker only delivers work."""

import logging

from celery import Celery, Task
from pymongo.errors import PyMongoError

from app.config import get_settings
from app.contracts import (
    APPLY_CREDIT_TASK,
    MAX_APPLY_RETRIES,
    RETRY_BACKOFF_MAX_SECONDS,
)

logger = logging.getLogger(__name__)


def create_celery() -> Celery:
    """Build a Celery app that uses Redis as the broker and ignores task results."""
    settings = get_settings()
    celery_app = Celery("basta", broker=settings.redis_url)
    celery_app.conf.update(
        task_acks_late=True,
        task_ignore_result=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        broker_connection_max_retries=3,
        broker_transport_options={
            "socket_timeout": 3,
            "socket_connect_timeout": 3,
            "retry_on_timeout": False,
        },
    )
    return celery_app


celery_app = create_celery()


@celery_app.task(
    name=APPLY_CREDIT_TASK,
    bind=True,
    autoretry_for=(PyMongoError, ConnectionError, TimeoutError),
    max_retries=MAX_APPLY_RETRIES,
    retry_backoff=True,
    retry_backoff_max=RETRY_BACKOFF_MAX_SECONDS,
    retry_jitter=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def apply_credit(self: Task, task_id: str) -> None:
    """Apply one credit exactly once by calling CreditService.apply.

    An already processed credit is a no-op. After the retry budget, mark the credit
    failed and acknowledge the message.
    """
    from app.api.deps import get_credit_service

    try:
        outcome = get_credit_service().apply(task_id)
    except Exception as exc:
        retries = int(getattr(self.request, "retries", 0) or 0)
        retryable = isinstance(exc, (PyMongoError, ConnectionError, TimeoutError))
        logger.exception("apply_credit failed task_id=%s retries=%s", task_id, retries)
        if not retryable or retries >= int(self.max_retries):
            _fail_after_retries(task_id, exc)
        raise
    logger.info("apply_credit finished task_id=%s outcome=%s", task_id, outcome.value)


def mark_credit_failed_after_retries(task_id: str, error: str) -> None:
    """Set the credit to failed once apply_credit has exhausted retries."""
    from app.db import get_database
    from app.repositories.credits import MongoCreditRepository

    updated = MongoCreditRepository(get_database(get_settings())).mark_failed(task_id, error)
    if updated:
        logger.error("credit marked failed after retries task_id=%s error=%s", task_id, error)
        return
    logger.warning("retry failure left credit unchanged task_id=%s error=%s", task_id, error)


def _fail_after_retries(task_id: str, exc: Exception) -> None:
    try:
        mark_credit_failed_after_retries(task_id, str(exc))
    except Exception:
        logger.exception("could not mark credit failed after retries task_id=%s", task_id)
