from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.deps import build_credit_service
from app.statuses import ApplyOutcome
from app.tasks import apply_credit, mark_credit_failed_after_retries
from tests.conftest import RecordingPublisher


def _user_id() -> str:
    return f"u_{uuid4().hex[:12]}"


def _post_credit(
    client: TestClient,
    user_id: str,
    amount: str,
    idempotency_key: str | None = None,
):
    headers = {}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return client.post(
        "/credits",
        json={"user_id": user_id, "amount": amount},
        headers=headers,
    )


def test_invalid_credit_is_rejected(client: TestClient) -> None:
    user_id = _user_id()
    assert _post_credit(client, user_id, "-1.00").status_code == 422
    assert client.post("/credits", json={"user_id": user_id, "amount": 1.25}).status_code == 422
    assert client.post("/credits", json={"user_id": "bad id", "amount": "1.00"}).status_code == 422
    assert client.post("/credits", json={"user_id": user_id, "amount": "1.234"}).status_code == 422


def test_credit_is_applied_once(client: TestClient, publisher: RecordingPublisher) -> None:
    user_id = _user_id()
    created = _post_credit(client, user_id, "25.00")
    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "processing"
    assert publisher.task_ids == [body["task_id"]]

    outcome = build_credit_service(publisher).apply(body["task_id"])
    assert outcome == ApplyOutcome.APPLIED
    again = build_credit_service(publisher).apply(body["task_id"])
    assert again == ApplyOutcome.ALREADY_PROCESSED

    credit = client.get(f"/credits/{body['task_id']}")
    assert credit.status_code == 200
    assert credit.json()["status"] == "processed"
    assert Decimal(credit.json()["amount"]) == Decimal("25.00")

    user = client.get(f"/users/{user_id}")
    assert user.status_code == 200
    assert Decimal(user.json()["balance"]) == Decimal("25.00")


def test_worker_entry_applies_balance(client: TestClient, publisher: RecordingPublisher) -> None:
    user_id = _user_id()
    created = _post_credit(client, user_id, "10.50")
    task_id = created.json()["task_id"]

    apply_credit(task_id)
    apply_credit(task_id)

    user = client.get(f"/users/{user_id}")
    assert Decimal(user.json()["balance"]) == Decimal("10.50")
    assert client.get(f"/credits/{task_id}").json()["status"] == "processed"


def test_balances_sum_across_credits(client: TestClient, publisher: RecordingPublisher) -> None:
    user_id = _user_id()
    first = _post_credit(client, user_id, "10.00").json()["task_id"]
    second = _post_credit(client, user_id, "5.25").json()["task_id"]
    service = build_credit_service(publisher)
    assert service.apply(first) == ApplyOutcome.APPLIED
    assert service.apply(second) == ApplyOutcome.APPLIED

    listed = client.get("/users")
    assert listed.status_code == 200
    balances = {row["user_id"]: Decimal(row["balance"]) for row in listed.json()["users"]}
    assert balances[user_id] == Decimal("15.25")


def test_idempotency_replays_the_same_task(client: TestClient, publisher: RecordingPublisher) -> None:
    user_id = _user_id()
    first = _post_credit(client, user_id, "8.00", idempotency_key="same-key")
    second = _post_credit(client, user_id, "8.00", idempotency_key="same-key")
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["task_id"] == second.json()["task_id"]
    assert publisher.task_ids == [first.json()["task_id"]]


def test_idempotency_conflict(client: TestClient, publisher: RecordingPublisher) -> None:
    user_id = _user_id()
    assert _post_credit(client, user_id, "8.00", idempotency_key="conflict-key").status_code == 202
    conflict = _post_credit(client, user_id, "9.00", idempotency_key="conflict-key")
    assert conflict.status_code == 409
    assert len(publisher.task_ids) == 1


def test_publish_failure_marks_credit_failed(client: TestClient, publisher: RecordingPublisher) -> None:
    publisher.error = ConnectionError("redis down")
    user_id = _user_id()
    response = _post_credit(client, user_id, "3.00")
    assert response.status_code == 503
    assert response.json()["detail"] == "Credit could not be queued"

    listed = client.get("/credits/missing")
    assert listed.status_code == 404
    from app.config import get_settings
    from app.contracts import CREDITS_COLLECTION
    from app.db import get_database

    stored = list(get_database(get_settings())[CREDITS_COLLECTION].find({"user_id": user_id}))
    assert len(stored) == 1
    assert stored[0]["status"] == "failed"
    assert stored[0]["error"] == "broker publish failed"


def test_missing_credit_and_user(client: TestClient) -> None:
    assert client.get("/credits/does-not-exist").status_code == 404
    assert client.get(f"/users/{_user_id()}").status_code == 404


def test_failed_retry_does_not_overwrite_processed_credit(
    client: TestClient,
    publisher: RecordingPublisher,
) -> None:
    user_id = _user_id()
    task_id = _post_credit(client, user_id, "4.00").json()["task_id"]
    apply_credit(task_id)
    mark_credit_failed_after_retries(task_id, "late failure")
    assert client.get(f"/credits/{task_id}").json()["status"] == "processed"
    assert Decimal(client.get(f"/users/{user_id}").json()["balance"]) == Decimal("4.00")


def test_real_broker_enqueue(client: TestClient) -> None:
    user_id = _user_id()
    created = _post_credit(client, user_id, "2.00")
    assert created.status_code == 202
    task_id = created.json()["task_id"]
    assert client.get(f"/credits/{task_id}").json()["status"] == "processing"
    apply_credit(task_id)
    assert client.get(f"/credits/{task_id}").json()["status"] == "processed"


def test_health_and_demo_page(client: TestClient) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"mongodb": "up", "redis": "up"}
    page = client.get("/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert 'name="user_id"' in page.text
    assert 'name="amount"' in page.text
    assert "Add credit" in page.text


def test_user_list_is_capped(client: TestClient) -> None:
    assert client.get("/users", params={"limit": 101}).status_code == 422
    assert client.get("/users", params={"limit": 100}).status_code == 200


def test_missing_apply_is_a_no_op(publisher: RecordingPublisher) -> None:
    assert build_credit_service(publisher).apply("missing-task") == ApplyOutcome.MISSING
