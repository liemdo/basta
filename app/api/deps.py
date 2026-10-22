"""Composition root."""

from app.config import get_settings
from app.db import MongoUnitOfWork, get_database, get_mongo_client, get_redis_client
from app.publishing import CeleryTaskPublisher, TaskPublisher
from app.repositories.credits import MongoCreditRepository
from app.repositories.users import MongoUserRepository
from app.services.credits import CreditApplication, CreditService
from app.services.health import DependencyHealth, HealthService


def build_credit_service(publisher: TaskPublisher | None = None) -> CreditService:
    """Wire repositories, the broker, and a MongoDB transaction."""
    settings = get_settings()
    database = get_database(settings)
    client = get_mongo_client(settings)
    return CreditApplication(
        credits=MongoCreditRepository(database),
        users=MongoUserRepository(database),
        publisher=publisher or CeleryTaskPublisher(),
        unit_of_work_factory=lambda: MongoUnitOfWork(client),
    )


def get_credit_service() -> CreditService:
    return build_credit_service()


def get_health_service() -> HealthService:
    settings = get_settings()
    return DependencyHealth(
        mongo=get_mongo_client(settings),
        redis_client=get_redis_client(settings),
    )
