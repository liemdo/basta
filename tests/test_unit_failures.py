"""Invalid input, conflicts, and network failures without a live database."""

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError
from starlette.responses import Response

from app.api import credits
from app.api.deps import get_credit_service
from app.api.errors import register_exception_handlers
from app.api.health import health
from app.exceptions import BrokerPublishError, CreditNotFound, IdempotencyConflict, UserNotFound
from app.publishing import CeleryTaskPublisher
from app.schemas import AcceptCredit, CreditCreate, HealthView
from app.services.health import DependencyHealth, HealthService
from app.statuses import ApplyOutcome, CreditStatus, DependencyStatus
from app.tasks import apply_credit
from tests.fakes import ServiceBundle


def _command(amount: str = "8.00", key: str | None = None) -> AcceptCredit:
    return AcceptCredit(user_id="u_123", amount=Decimal(amount), idempotency_key=key)


def test_invalid_amounts_and_user_ids_are_rejected() -> None:
    rejected = [
        {"user_id": "u_123", "amount": "-1.00"},
        {"user_id": "u_123", "amount": "0"},
        {"user_id": "u_123", "amount": "1.234"},
        {"user_id": "u_123", "amount": 1.25},
        {"user_id": "u_123", "amount": True},
        {"user_id": "u_123", "amount": "1000000.01"},
        {"user_id": "bad id", "amount": "1.00"},
        {"user_id": "", "amount": "1.00"},
    ]
    for payload in rejected:
        with pytest.raises(ValidationError):
            CreditCreate.model_validate(payload)

    created = CreditCreate.model_validate({"user_id": "u_123", "amount": "25.00"})
    assert created.amount == Decimal("25.00")


def test_idempotency_key_with_a_different_body_conflicts() -> None:
    bundle = ServiceBundle()
    bundle.service.accept(_command(amount="8.00", key="once"))
    with pytest.raises(IdempotencyConflict):
        bundle.service.accept(_command(amount="9.00", key="once"))
    assert len(bundle.publisher.task_ids) == 1


def test_broker_outage_marks_the_credit_failed() -> None:
    bundle = ServiceBundle()
    bundle.publisher.error = ConnectionError("redis down")

    with pytest.raises(BrokerPublishError):
        bundle.service.accept(_command())

    stored = next(iter(bundle.credits.rows.values()))
    assert stored.status == CreditStatus.FAILED
    assert stored.error == "broker publish failed"
    assert bundle.publisher.task_ids == []


def test_broker_outage_still_raises_when_the_failure_write_fails() -> None:
    bundle = ServiceBundle()
    bundle.publisher.error = TimeoutError("timed out")
    bundle.credits.fail_writes = True

    with pytest.raises(BrokerPublishError):
        bundle.service.accept(_command())


def test_unrelated_duplicate_key_is_not_hidden() -> None:
    bundle = ServiceBundle()

    def explode(credit):
        raise DuplicateKeyError("task id collision")

    bundle.credits.insert_processing = explode  # type: ignore[method-assign]
    with pytest.raises(DuplicateKeyError):
        bundle.service.accept(_command())


def test_unknown_credit_and_user_raise() -> None:
    bundle = ServiceBundle()
    with pytest.raises(CreditNotFound):
        bundle.service.get_credit("missing")
    with pytest.raises(UserNotFound):
        bundle.service.get_user("missing")


def test_terminal_credit_is_not_applied_again() -> None:
    bundle = ServiceBundle()
    accepted = bundle.service.accept(_command())
    bundle.credits.rows[accepted.task_id] = bundle.credits.rows[accepted.task_id].model_copy(
        update={"status": CreditStatus.FAILED, "error": "stopped"}
    )

    assert bundle.service.apply(accepted.task_id) == ApplyOutcome.ALREADY_PROCESSED
    assert bundle.users.rows == {}
    assert bundle.unit_of_work.committed is False


def test_lost_claim_does_not_increment_the_balance() -> None:
    bundle = ServiceBundle()
    accepted = bundle.service.accept(_command())
    bundle.credits.mark_processed = lambda task_id: False  # type: ignore[method-assign]

    assert bundle.service.apply(accepted.task_id) == ApplyOutcome.ALREADY_PROCESSED
    assert bundle.users.rows == {}
    assert bundle.unit_of_work.aborted is True


def test_database_outage_during_apply_aborts_the_transaction() -> None:
    bundle = ServiceBundle()
    accepted = bundle.service.accept(_command())
    bundle.users.fail_increment = True

    with pytest.raises(ConnectionError):
        bundle.service.apply(accepted.task_id)
    assert bundle.unit_of_work.aborted is True
    assert bundle.users.rows == {}


def test_user_list_is_clamped() -> None:
    bundle = ServiceBundle()
    bundle.service.list_users(0)
    bundle.service.list_users(1000)
    assert bundle.users.limits == [1, 100]


class _Ping:
    def __init__(self, error: Exception | None = None, ok: bool = True) -> None:
        self.error = error
        self.ok = ok
        self.admin = self

    def command(self, _name: str) -> dict[str, int]:
        if self.error is not None:
            raise self.error
        return {"ok": 1}

    def ping(self) -> bool:
        if self.error is not None:
            raise self.error
        return self.ok


def test_health_reports_a_down_dependency() -> None:
    mongo_down = DependencyHealth(mongo=_Ping(error=ConnectionError("mongo down")), redis_client=_Ping())  # type: ignore[arg-type]
    redis_down = DependencyHealth(mongo=_Ping(), redis_client=_Ping(ok=False))  # type: ignore[arg-type]

    assert mongo_down.check().mongodb == DependencyStatus.DOWN
    assert mongo_down.check().redis == DependencyStatus.UP
    assert redis_down.check().redis == DependencyStatus.DOWN


def test_health_route_uses_503_when_a_dependency_is_down() -> None:
    class Down(HealthService):
        def check(self) -> HealthView:
            return HealthView(mongodb=DependencyStatus.DOWN, redis=DependencyStatus.UP)

    response = Response()
    report = health(response, Down())
    assert response.status_code == 503
    assert report.mongodb == DependencyStatus.DOWN


def test_publisher_reraises_a_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(_task_id: str) -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr("app.tasks.apply_credit.delay", down)
    with pytest.raises(ConnectionError):
        CeleryTaskPublisher().publish_apply_credit("task-1")


def test_worker_marks_a_non_retryable_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[tuple[str, str]] = []

    class Boom:
        def apply(self, _task_id: str) -> None:
            raise RuntimeError("bad state")

    monkeypatch.setattr("app.api.deps.get_credit_service", lambda: Boom())
    monkeypatch.setattr(
        "app.tasks.mark_credit_failed_after_retries",
        lambda task_id, error: recorded.append((task_id, error)),
    )

    with pytest.raises(RuntimeError):
        apply_credit("task-1")
    assert recorded == [("task-1", "bad state")]


def test_worker_keeps_a_retryable_failure_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[tuple[str, str]] = []

    class Boom:
        def apply(self, _task_id: str) -> None:
            raise ConnectionError("mongo reset")

    monkeypatch.setattr("app.api.deps.get_credit_service", lambda: Boom())
    monkeypatch.setattr(
        "app.tasks.mark_credit_failed_after_retries",
        lambda task_id, error: recorded.append((task_id, error)),
    )

    with pytest.raises(ConnectionError):
        apply_credit("task-1")
    assert recorded == []


def test_http_maps_success_and_failures() -> None:
    bundle = ServiceBundle()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(credits.router)
    app.dependency_overrides[get_credit_service] = lambda: bundle.service

    with TestClient(app) as client:
        created = client.post("/credits", json={"user_id": "u_123", "amount": "25.00"})
        assert created.status_code == 202
        task_id = created.json()["task_id"]
        assert client.get(f"/credits/{task_id}").json()["status"] == "processing"

        invalid = client.post("/credits", json={"user_id": "u_123", "amount": "-2.00"})
        assert invalid.status_code == 422

        missing = client.get("/credits/missing")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "Credit not found"

        bundle.publisher.error = ConnectionError("redis down")
        queued = client.post("/credits", json={"user_id": "u_999", "amount": "1.00"})
        assert queued.status_code == 503
        assert queued.json()["detail"] == "Credit could not be queued"
