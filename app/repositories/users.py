from abc import ABC, abstractmethod
from decimal import Decimal

from pymongo import DESCENDING
from pymongo.database import Database

from app.clock import utcnow
from app.contracts import USERS_COLLECTION
from app.db import current_session
from app.money import from_decimal128, to_decimal128
from app.schemas import UserRecord


class UserRepository(ABC):
    """Persistence for user balances."""

    @abstractmethod
    def get(self, user_id: str) -> UserRecord | None:
        """Return the user, or None when no balance document exists."""

    @abstractmethod
    def list_recent(self, limit: int) -> list[UserRecord]:
        """Return up to `limit` users, most recently updated first."""

    @abstractmethod
    def increment_balance(self, user_id: str, amount: Decimal) -> UserRecord:
        """Add `amount` to the balance, creating the user at that balance when missing.

        Callers run this inside the same transaction that marks the credit processed.
        """


class MongoUserRepository(UserRepository):
    def __init__(self, database: Database) -> None:
        self._database = database

    def get(self, user_id: str) -> UserRecord | None:
        document = self._collection().find_one({"user_id": user_id}, session=current_session())
        if document is None:
            return None
        return _user_from_document(document)

    def list_recent(self, limit: int) -> list[UserRecord]:
        cursor = (
            self._collection()
            .find(session=current_session())
            .sort("updated_at", DESCENDING)
            .limit(limit)
        )
        return [_user_from_document(document) for document in cursor]

    def increment_balance(self, user_id: str, amount: Decimal) -> UserRecord:
        self._collection().update_one(
            {"user_id": user_id},
            {
                "$inc": {"balance": to_decimal128(amount)},
                "$set": {"updated_at": utcnow()},
            },
            upsert=True,
            session=current_session(),
        )
        document = self._collection().find_one({"user_id": user_id}, session=current_session())
        if document is None:
            raise RuntimeError(f"balance missing after increment user_id={user_id}")
        return _user_from_document(document)

    def _collection(self):
        return self._database[USERS_COLLECTION]


def _user_from_document(document: dict) -> UserRecord:
    return UserRecord(
        user_id=document["user_id"],
        balance=from_decimal128(document["balance"]),
        updated_at=document.get("updated_at"),
    )
