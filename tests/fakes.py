"""In-memory stand-ins so service tests do not open MongoDB or Redis."""

from decimal import Decimal

from pymongo.errors import DuplicateKeyError

from app.clock import utcnow
from app.db import UnitOfWork
from app.publishing import TaskPublisher
from app.repositories.credits import CreditRepository
from app.repositories.users import UserRepository
from app.schemas import CreditRecord, NewCredit, UserRecord
from app.services.credits import CreditApplication
from app.statuses import CreditStatus


class MemoryCredits(CreditRepository):
    def __init__(self) -> None:
        self.rows: dict[str, CreditRecord] = {}
        self.fail_writes = False

    def insert_processing(self, credit: NewCredit) -> CreditRecord:
        if credit.idempotency_key and self.get_by_idempotency_key(credit.idempotency_key):
            raise DuplicateKeyError("duplicate idempotency key")
        record = CreditRecord(
            task_id=credit.task_id,
            user_id=credit.user_id,
            amount=credit.amount,
            status=CreditStatus.PROCESSING,
            idempotency_key=credit.idempotency_key,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        self.rows[credit.task_id] = record
        return record

    def get(self, task_id: str) -> CreditRecord | None:
        return self.rows.get(task_id)

    def get_by_idempotency_key(self, key: str) -> CreditRecord | None:
        for record in self.rows.values():
            if record.idempotency_key == key:
                return record
        return None

    def mark_processed(self, task_id: str) -> bool:
        record = self.rows.get(task_id)
        if record is None or record.status != CreditStatus.PROCESSING:
            return False
        self.rows[task_id] = record.model_copy(
            update={"status": CreditStatus.PROCESSED, "updated_at": utcnow()}
        )
        return True

    def mark_failed(self, task_id: str, error: str) -> bool:
        if self.fail_writes:
            raise ConnectionError("database unreachable")
        record = self.rows.get(task_id)
        if record is None or record.status != CreditStatus.PROCESSING:
            return False
        self.rows[task_id] = record.model_copy(
            update={"status": CreditStatus.FAILED, "error": error, "updated_at": utcnow()}
        )
        return True


class MemoryUsers(UserRepository):
    def __init__(self) -> None:
        self.rows: dict[str, UserRecord] = {}
        self.limits: list[int] = []
        self.fail_increment = False

    def get(self, user_id: str) -> UserRecord | None:
        return self.rows.get(user_id)

    def list_recent(self, limit: int) -> list[UserRecord]:
        self.limits.append(limit)
        ordered = sorted(
            self.rows.values(),
            key=lambda record: record.updated_at or record.user_id,
            reverse=True,
        )
        return ordered[:limit]

    def increment_balance(self, user_id: str, amount: Decimal) -> UserRecord:
        if self.fail_increment:
            raise ConnectionError("database unreachable")
        current = self.rows.get(user_id)
        balance = (current.balance if current else Decimal("0")) + amount
        record = UserRecord(user_id=user_id, balance=balance, updated_at=utcnow())
        self.rows[user_id] = record
        return record


class MemoryPublisher(TaskPublisher):
    def __init__(self) -> None:
        self.task_ids: list[str] = []
        self.error: Exception | None = None

    def publish_apply_credit(self, task_id: str) -> None:
        if self.error is not None:
            raise self.error
        self.task_ids.append(task_id)


class MemoryUnitOfWork(UnitOfWork):
    def __init__(self) -> None:
        self.committed = False
        self.aborted = False

    def __enter__(self) -> "MemoryUnitOfWork":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            self.committed = True
        else:
            self.aborted = True
        return None


class ServiceBundle:
    def __init__(self) -> None:
        self.credits = MemoryCredits()
        self.users = MemoryUsers()
        self.publisher = MemoryPublisher()
        self.unit_of_work = MemoryUnitOfWork()
        self.service = CreditApplication(
            credits=self.credits,
            users=self.users,
            publisher=self.publisher,
            unit_of_work_factory=lambda: self.unit_of_work,
        )
