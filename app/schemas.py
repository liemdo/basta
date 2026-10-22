"""Domain and HTTP models. These types are the public and storage contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.contracts import (
    MAX_CREDIT_AMOUNT,
    MAX_IDEMPOTENCY_KEY_LENGTH,
    MAX_USER_ID_LENGTH,
    USER_ID_PATTERN,
)
from app.statuses import CreditStatus, DependencyStatus

UserId = Annotated[
    str,
    Field(min_length=1, max_length=MAX_USER_ID_LENGTH, pattern=USER_ID_PATTERN),
]
IdempotencyKey = Annotated[str, Field(min_length=1, max_length=MAX_IDEMPOTENCY_KEY_LENGTH)]


def parse_money(value: object) -> Decimal:
    """Accept a decimal string or int. Reject JSON floats so money is not binary."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("amount must be a decimal string")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("amount must be a decimal string")


Money = Annotated[
    Decimal,
    BeforeValidator(parse_money),
    Field(gt=0, le=MAX_CREDIT_AMOUNT, max_digits=12, decimal_places=2),
]


class CreditCreate(BaseModel):
    """Body of POST /credits."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"user_id": "u_123", "amount": "25.00"}]},
    )

    user_id: UserId
    amount: Money


class AcceptCredit(BaseModel):
    """Service input for accepting one credit."""

    model_config = ConfigDict(extra="forbid")

    user_id: UserId
    amount: Money
    idempotency_key: IdempotencyKey | None = None


class CreditAccepted(BaseModel):
    """202 response. Status is processing until the worker finishes."""

    task_id: str
    status: CreditStatus


class CreditView(BaseModel):
    """GET /credits/{task_id} response."""

    task_id: str
    user_id: str
    amount: Decimal
    status: CreditStatus
    error: str | None = None


class UserView(BaseModel):
    """One user's committed balance."""

    user_id: str
    balance: Decimal


class UserListView(BaseModel):
    """GET /users response. At most 100 users, most recently updated first."""

    users: list[UserView]


class HealthView(BaseModel):
    """GET /health response. 503 when either dependency is down."""

    mongodb: DependencyStatus
    redis: DependencyStatus


class ErrorView(BaseModel):
    detail: str


class NewCredit(BaseModel):
    """Document inserted while a credit is waiting for the worker."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    user_id: str
    amount: Decimal
    idempotency_key: str | None = None


class CreditRecord(BaseModel):
    """Stored credit. Status lives here, not on the user."""

    task_id: str
    user_id: str
    amount: Decimal
    status: CreditStatus
    idempotency_key: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserRecord(BaseModel):
    """Stored user. Balance is Decimal128 in MongoDB."""

    user_id: str
    balance: Decimal
    updated_at: datetime | None = None
