import logging
from abc import ABC, abstractmethod

from pymongo.mongo_client import MongoClient
from redis import Redis

from app.schemas import HealthView
from app.statuses import DependencyStatus

logger = logging.getLogger(__name__)


class HealthService(ABC):
    @abstractmethod
    def check(self) -> HealthView:
        """Ping MongoDB and Redis. Either dependency down is a failed check."""


class DependencyHealth(HealthService):
    def __init__(self, mongo: MongoClient, redis_client: Redis) -> None:
        self._mongo = mongo
        self._redis = redis_client

    def check(self) -> HealthView:
        return HealthView(mongodb=_mongo_status(self._mongo), redis=_redis_status(self._redis))


def _mongo_status(client: MongoClient) -> DependencyStatus:
    try:
        client.admin.command("ping")
    except Exception:
        logger.exception("MongoDB health check failed")
        return DependencyStatus.DOWN
    return DependencyStatus.UP


def _redis_status(client: Redis) -> DependencyStatus:
    try:
        if client.ping():
            return DependencyStatus.UP
    except Exception:
        logger.exception("Redis health check failed")
        return DependencyStatus.DOWN
    logger.error("Redis health check returned false")
    return DependencyStatus.DOWN
