"""MongoDB and Redis clients, indexes, and the credit transaction."""

import logging
from abc import ABC, abstractmethod
from contextvars import ContextVar, Token

from pymongo import ASCENDING, IndexModel
from pymongo.client_session import ClientSession
from pymongo.database import Database
from pymongo.mongo_client import MongoClient
from redis import Redis

from app.config import Settings
from app.contracts import CREDITS_COLLECTION, USERS_COLLECTION

logger = logging.getLogger(__name__)

USER_INDEXES: tuple[IndexModel, ...] = (
    IndexModel([("user_id", ASCENDING)], unique=True, name="user_id_unique"),
)

CREDIT_INDEXES: tuple[IndexModel, ...] = (
    IndexModel(
        [("idempotency_key", ASCENDING)],
        unique=True,
        sparse=True,
        name="idempotency_key_unique",
    ),
    IndexModel([("user_id", ASCENDING)], name="credits_user_id"),
)

COLLECTION_INDEXES: dict[str, tuple[IndexModel, ...]] = {
    USERS_COLLECTION: USER_INDEXES,
    CREDITS_COLLECTION: CREDIT_INDEXES,
}

_mongo_clients: dict[str, MongoClient] = {}
_redis_clients: dict[str, Redis] = {}
_indexes_ready: set[str] = set()
_session: ContextVar[ClientSession | None] = ContextVar("mongo_session", default=None)


def current_session() -> ClientSession | None:
    """Return the transaction session started by MongoUnitOfWork, if any."""
    return _session.get()


def get_mongo_client(settings: Settings) -> MongoClient:
    """Open the MongoDB client from `MONGODB_URI`."""
    client = _mongo_clients.get(settings.mongodb_uri)
    if client is None:
        client = MongoClient(
            settings.mongodb_uri,
            tz_aware=True,
            serverSelectionTimeoutMS=3000,
        )
        _mongo_clients[settings.mongodb_uri] = client
    return client


def get_database(settings: Settings) -> Database:
    """Return the application database and ensure indexes once per process."""
    database = get_mongo_client(settings)[settings.mongodb_database]
    if settings.mongodb_database not in _indexes_ready:
        ensure_indexes(database)
        _indexes_ready.add(settings.mongodb_database)
    return database


def ensure_indexes(database: Database) -> None:
    """Create user and credit indexes. Safe to call more than once."""
    try:
        for name, indexes in COLLECTION_INDEXES.items():
            database[name].create_indexes(list(indexes))
    except Exception:
        logger.exception("failed to create indexes database=%s", database.name)
        raise
    logger.info("indexes ensured database=%s", database.name)


def get_redis_client(settings: Settings) -> Redis:
    """Open the Redis client from `REDIS_URL`."""
    client = _redis_clients.get(settings.redis_url)
    if client is None:
        client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        _redis_clients[settings.redis_url] = client
    return client


def close_clients() -> None:
    """Close cached clients. The next call opens fresh ones."""
    for client in _mongo_clients.values():
        client.close()
    _mongo_clients.clear()
    for client in _redis_clients.values():
        client.close()
    _redis_clients.clear()
    _indexes_ready.clear()


class UnitOfWork(ABC):
    """One MongoDB transaction covering the credit status flip and the balance increment."""

    @abstractmethod
    def __enter__(self) -> "UnitOfWork":
        """Start a transaction."""

    @abstractmethod
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Commit when there is no error, otherwise abort."""


class MongoUnitOfWork(UnitOfWork):
    def __init__(self, client: MongoClient) -> None:
        self._client = client
        self._mongo_session: ClientSession | None = None
        self._token: Token[ClientSession | None] | None = None

    def __enter__(self) -> "MongoUnitOfWork":
        session = self._client.start_session()
        try:
            session.start_transaction()
        except Exception:
            session.end_session()
            logger.exception("failed to start credit transaction")
            raise
        self._mongo_session = session
        self._token = _session.set(session)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        session = self._mongo_session
        if session is None:
            return None
        try:
            if exc_type is None:
                session.commit_transaction()
            else:
                session.abort_transaction()
        except Exception:
            logger.exception("failed to finish credit transaction")
            raise
        finally:
            session.end_session()
            self._mongo_session = None
            if self._token is not None:
                _session.reset(self._token)
                self._token = None
        return None
