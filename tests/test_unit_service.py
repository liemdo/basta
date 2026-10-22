"""Unit tests for the credit use cases. No database or broker is opened."""

from decimal import Decimal

from pymongo.errors import DuplicateKeyError

from app.schemas import AcceptCredit
from app.statuses import ApplyOutcome, CreditStatus
from tests.fakes import ServiceBundle


def _command(user_id: str = "u_123", amount: str = "25.00", key: str | None = None) -> AcceptCredit:
    return AcceptCredit(user_id=user_id, amount=Decimal(amount), idempotency_key=key)


def test_accept_publishes_a_processing_credit() -> None:
    bundle = ServiceBundle()
    accepted = bundle.service.accept(_command())

    assert accepted.status == CreditStatus.PROCESSING
    assert bundle.publisher.task_ids == [accepted.task_id]
    stored = bundle.service.get_credit(accepted.task_id)
    assert stored.user_id == "u_123"
    assert stored.amount == Decimal("25.00")
    assert stored.status == CreditStatus.PROCESSING


def test_apply_adds_the_amount_once() -> None:
    bundle = ServiceBundle()
    accepted = bundle.service.accept(_command(amount="10.50"))

    assert bundle.service.apply(accepted.task_id) == ApplyOutcome.APPLIED
    assert bundle.service.apply(accepted.task_id) == ApplyOutcome.ALREADY_PROCESSED

    user = bundle.service.get_user("u_123")
    assert user.balance == Decimal("10.50")
    assert bundle.unit_of_work.committed is True
    assert bundle.service.get_credit(accepted.task_id).status == CreditStatus.PROCESSED


def test_balances_sum_across_credits() -> None:
    bundle = ServiceBundle()
    first = bundle.service.accept(_command(amount="10.00"))
    second = bundle.service.accept(_command(amount="5.25"))
    bundle.service.apply(first.task_id)
    bundle.service.apply(second.task_id)

    assert bundle.service.get_user("u_123").balance == Decimal("15.25")
    listed = bundle.service.list_users(limit=100)
    assert [user.user_id for user in listed.users] == ["u_123"]


def test_same_idempotency_key_replays_the_original_task() -> None:
    bundle = ServiceBundle()
    first = bundle.service.accept(_command(key="same-key"))
    second = bundle.service.accept(_command(key="same-key"))

    assert second.task_id == first.task_id
    assert bundle.publisher.task_ids == [first.task_id]


def test_duplicate_insert_replays_the_original_task() -> None:
    bundle = ServiceBundle()
    original = bundle.service.accept(_command(key="race-key"))
    lookup = bundle.credits.get_by_idempotency_key
    seen = {"calls": 0}

    def miss_once(key: str):
        seen["calls"] += 1
        if seen["calls"] == 1:
            return None
        return lookup(key)

    def collide(_credit):
        raise DuplicateKeyError("duplicate idempotency key")

    bundle.credits.get_by_idempotency_key = miss_once  # type: ignore[method-assign]
    bundle.credits.insert_processing = collide  # type: ignore[method-assign]

    replayed = bundle.service.accept(_command(key="race-key"))
    assert replayed.task_id == original.task_id


def test_missing_credit_apply_does_not_change_a_balance() -> None:
    bundle = ServiceBundle()
    assert bundle.service.apply("missing") == ApplyOutcome.MISSING
    assert bundle.users.rows == {}
