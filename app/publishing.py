import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class TaskPublisher(ABC):
    """Enqueue ``credits.apply_credit``. MongoDB remains the status source of truth."""

    @abstractmethod
    def publish_apply_credit(self, task_id: str) -> None:
        """Publish the apply task. Raise when the broker rejects the message."""


class CeleryTaskPublisher(TaskPublisher):
    def publish_apply_credit(self, task_id: str) -> None:
        from app.tasks import apply_credit

        try:
            apply_credit.delay(task_id)
        except Exception:
            logger.exception("failed to enqueue apply_credit task_id=%s", task_id)
            raise
        logger.info("enqueued apply_credit task_id=%s", task_id)
