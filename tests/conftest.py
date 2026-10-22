import os

os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/?directConnection=true")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["MONGODB_DATABASE"] = "credits_test"

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.deps import build_credit_service, get_credit_service
from app.config import get_settings
from app.contracts import CREDITS_COLLECTION, USERS_COLLECTION
from app.db import close_clients, get_database
from app.main import app
from app.publishing import TaskPublisher


class RecordingPublisher(TaskPublisher):
    def __init__(self) -> None:
        self.task_ids: list[str] = []
        self.error: Exception | None = None

    def publish_apply_credit(self, task_id: str) -> None:
        if self.error is not None:
            raise self.error
        self.task_ids.append(task_id)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides.clear()
    with TestClient(app) as test_client:
        database = get_database(get_settings())
        database[USERS_COLLECTION].delete_many({})
        database[CREDITS_COLLECTION].delete_many({})
        yield test_client
    app.dependency_overrides.clear()
    close_clients()


@pytest.fixture
def publisher(client: TestClient) -> RecordingPublisher:
    recording = RecordingPublisher()
    app.dependency_overrides[get_credit_service] = lambda: build_credit_service(recording)
    return recording
