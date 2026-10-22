import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.contracts import MAX_USER_LIST
from app.db import UnitOfWork
from app.exceptions import BrokerPublishError, CreditNotFound, IdempotencyConflict, UserNotFound
from app.publishing import TaskPublisher
from app.repositories.credits import CreditRepository
from app.repositories.users import UserRepository
from app.schemas import (
    AcceptCredit,
    CreditAccepted,
    CreditRecord,
    CreditView,
    NewCredit,
    UserListView,
    UserRecord,
    UserView,
)
from app.statuses import ApplyOutcome, CreditStatus

logger = logging.getLogger(__name__)


class _ClaimLost(Exception):
    """Another worker already moved this credit out of processing."""


class CreditService(ABC):
    """Use cases behind the credit API and the worker."""

    def __init__(
        self,
        credits: CreditRepository,
        users: UserRepository,
        publisher: TaskPublisher,
        unit_of_work_factory: Callable[[], UnitOfWork],
    ) -> None:
        self._credits = credits
        self._users = users
        self._publisher = publisher
        self._unit_of_work_factory = unit_of_work_factory

    @abstractmethod
    def accept(self, command: AcceptCredit) -> CreditAccepted:
        """Persist a processing credit, publish the apply task, and return its task id.

        The same idempotency key and body return the original task. The same key with
        a different body raises IdempotencyConflict. A broker failure marks the credit
        failed and raises BrokerPublishError.
        """

    @abstractmethod
    def get_credit(self, task_id: str) -> CreditView:
        """Return one credit. Raise CreditNotFound when the task id is unknown."""

    @abstractmethod
    def get_user(self, user_id: str) -> UserView:
        """Return the committed balance. Raise UserNotFound when the user has none."""

    @abstractmethod
    def list_users(self, limit: int) -> UserListView:
        """Return users who have a balance, most recently updated first."""

    @abstractmethod
    def apply(self, task_id: str) -> ApplyOutcome:
        """Increment the balance and set the credit processed in one transaction.

        An already processed credit returns ALREADY_PROCESSED and does not change the
        balance. An unknown task id returns MISSING.
        """


class CreditApplication(CreditService):
    def accept(self, command: AcceptCredit) -> CreditAccepted:
        replay = self._replay(command)
        if replay is not None:
            return replay

        task_id = str(uuid4())
        try:
            self._credits.insert_processing(
                NewCredit(
                    task_id=task_id,
                    user_id=command.user_id,
                    amount=command.amount,
                    idempotency_key=command.idempotency_key,
                )
            )
        except DuplicateKeyError:
            replay = self._replay(command)
            if replay is not None:
                return replay
            logger.exception("duplicate credit insert task_id=%s", task_id)
            raise

        self._publish_or_fail(task_id)
        logger.info(
            "accepted credit task_id=%s user_id=%s amount=%s",
            task_id,
            command.user_id,
            command.amount,
        )
        return CreditAccepted(task_id=task_id, status=CreditStatus.PROCESSING)

    def get_credit(self, task_id: str) -> CreditView:
        record = self._credits.get(task_id)
        if record is None:
            logger.info("credit not found task_id=%s", task_id)
            raise CreditNotFound(task_id)
        return _credit_view(record)

    def get_user(self, user_id: str) -> UserView:
        record = self._users.get(user_id)
        if record is None:
            logger.info("user not found user_id=%s", user_id)
            raise UserNotFound(user_id)
        return _user_view(record)

    def list_users(self, limit: int) -> UserListView:
        bounded = min(max(limit, 1), MAX_USER_LIST)
        records = self._users.list_recent(bounded)
        return UserListView(users=[_user_view(record) for record in records])

    def apply(self, task_id: str) -> ApplyOutcome:
        credit = self._credits.get(task_id)
        if credit is None:
            logger.warning("credit missing task_id=%s", task_id)
            return ApplyOutcome.MISSING
        if credit.status != CreditStatus.PROCESSING:
            logger.info(
                "credit not applied task_id=%s status=%s",
                task_id,
                credit.status.value,
            )
            return ApplyOutcome.ALREADY_PROCESSED

        try:
            with self._unit_of_work_factory():
                if not self._credits.mark_processed(task_id):
                    raise _ClaimLost()
                self._users.increment_balance(credit.user_id, credit.amount)
        except _ClaimLost:
            logger.info("credit claim lost task_id=%s", task_id)
            return ApplyOutcome.ALREADY_PROCESSED

        logger.info(
            "credit applied task_id=%s user_id=%s amount=%s",
            task_id,
            credit.user_id,
            credit.amount,
        )
        return ApplyOutcome.APPLIED

    def _replay(self, command: AcceptCredit) -> CreditAccepted | None:
        if command.idempotency_key is None:
            return None
        existing = self._credits.get_by_idempotency_key(command.idempotency_key)
        if existing is None:
            return None
        if existing.user_id != command.user_id or existing.amount != command.amount:
            logger.warning(
                "idempotency conflict key=%s task_id=%s",
                command.idempotency_key,
                existing.task_id,
            )
            raise IdempotencyConflict(command.idempotency_key)
        logger.info(
            "idempotency replay key=%s task_id=%s status=%s",
            command.idempotency_key,
            existing.task_id,
            existing.status.value,
        )
        return CreditAccepted(task_id=existing.task_id, status=existing.status)

    def _publish_or_fail(self, task_id: str) -> None:
        try:
            self._publisher.publish_apply_credit(task_id)
        except Exception as exc:
            logger.error("broker publish failed task_id=%s", task_id)
            try:
                if not self._credits.mark_failed(task_id, "broker publish failed"):
                    logger.error(
                        "publish failed and credit was not marked failed task_id=%s",
                        task_id,
                    )
            except Exception:
                logger.exception("could not mark credit failed after publish error task_id=%s", task_id)
            raise BrokerPublishError(task_id) from exc


def _credit_view(record: CreditRecord) -> CreditView:
    return CreditView(
        task_id=record.task_id,
        user_id=record.user_id,
        amount=record.amount,
        status=record.status,
        error=record.error,
    )


def _user_view(record: UserRecord) -> UserView:
    return UserView(user_id=record.user_id, balance=record.balance)
