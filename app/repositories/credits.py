import logging
from abc import ABC, abstractmethod

from pymongo.database import Database

from app.clock import utcnow
from app.contracts import CREDITS_COLLECTION, STORED_ERROR_MAX_LENGTH
from app.db import current_session
from app.money import from_decimal128, to_decimal128
from app.schemas import CreditRecord, NewCredit
from app.statuses import CreditStatus

logger = logging.getLogger(__name__)


class CreditRepository(ABC):
    """Persistence for credit documents. Balance does not live here."""

    @abstractmethod
    def insert_processing(self, credit: NewCredit) -> CreditRecord:
        """Insert a credit with status processing. The task id is the document id."""

    @abstractmethod
    def get(self, task_id: str) -> CreditRecord | None:
        """Return the credit, or None when the task id is unknown."""

    @abstractmethod
    def get_by_idempotency_key(self, key: str) -> CreditRecord | None:
        """Return the credit stored under this idempotency key, or None."""

    @abstractmethod
    def mark_processed(self, task_id: str) -> bool:
        """Set status from processing to processed. Return False when the credit was not processing."""

    @abstractmethod
    def mark_failed(self, task_id: str, error: str) -> bool:
        """Set status to failed when the credit is still processing.

        Return False when the credit is missing or already terminal, so a late
        failure cannot overwrite a processed balance update.
        """


class MongoCreditRepository(CreditRepository):
    def __init__(self, database: Database) -> None:
        self._database = database

    def insert_processing(self, credit: NewCredit) -> CreditRecord:
        now = utcnow()
        document: dict[str, object] = {
            "_id": credit.task_id,
            "user_id": credit.user_id,
            "amount": to_decimal128(credit.amount),
            "status": CreditStatus.PROCESSING.value,
            "created_at": now,
            "updated_at": now,
        }
        if credit.idempotency_key is not None:
            document["idempotency_key"] = credit.idempotency_key
        self._collection().insert_one(document)
        return CreditRecord(
            task_id=credit.task_id,
            user_id=credit.user_id,
            amount=credit.amount,
            status=CreditStatus.PROCESSING,
            idempotency_key=credit.idempotency_key,
            created_at=now,
            updated_at=now,
        )

    def get(self, task_id: str) -> CreditRecord | None:
        document = self._collection().find_one({"_id": task_id}, session=current_session())
        if document is None:
            return None
        return _credit_from_document(document)

    def get_by_idempotency_key(self, key: str) -> CreditRecord | None:
        document = self._collection().find_one(
            {"idempotency_key": key},
            session=current_session(),
        )
        if document is None:
            return None
        return _credit_from_document(document)

    def mark_processed(self, task_id: str) -> bool:
        result = self._collection().update_one(
            {"_id": task_id, "status": CreditStatus.PROCESSING.value},
            {
                "$set": {
                    "status": CreditStatus.PROCESSED.value,
                    "updated_at": utcnow(),
                }
            },
            session=current_session(),
        )
        return result.modified_count == 1

    def mark_failed(self, task_id: str, error: str) -> bool:
        result = self._collection().update_one(
            {"_id": task_id, "status": CreditStatus.PROCESSING.value},
            {
                "$set": {
                    "status": CreditStatus.FAILED.value,
                    "error": _stored_error(error),
                    "updated_at": utcnow(),
                }
            },
            session=current_session(),
        )
        if result.modified_count != 1:
            logger.warning("credit not marked failed task_id=%s", task_id)
            return False
        return True

    def _collection(self):
        return self._database[CREDITS_COLLECTION]


def _credit_from_document(document: dict) -> CreditRecord:
    return CreditRecord(
        task_id=str(document["_id"]),
        user_id=document["user_id"],
        amount=from_decimal128(document["amount"]),
        status=CreditStatus(document["status"]),
        idempotency_key=document.get("idempotency_key"),
        error=document.get("error"),
        created_at=document.get("created_at"),
        updated_at=document.get("updated_at"),
    )


def _stored_error(error: str) -> str:
    cleaned = " ".join(error.split())
    if len(cleaned) <= STORED_ERROR_MAX_LENGTH:
        return cleaned
    return cleaned[: STORED_ERROR_MAX_LENGTH - 3] + "..."
