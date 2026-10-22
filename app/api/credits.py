from typing import Annotated

from fastapi import APIRouter, Depends, Header, status

from app.api.deps import get_credit_service
from app.schemas import AcceptCredit, CreditAccepted, CreditCreate, CreditView, ErrorView
from app.services.credits import CreditService

router = APIRouter(prefix="/credits", tags=["credits"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CreditAccepted,
    responses={
        status.HTTP_409_CONFLICT: {"model": ErrorView},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorView},
    },
)
def create_credit(
    body: CreditCreate,
    service: Annotated[CreditService, Depends(get_credit_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CreditAccepted:
    """Validate the credit, store it as processing, publish the task, and return 202.

    The same Idempotency-Key and body replay the original task (202). The same key
    with a different body is 409. A broker failure is 503 and the credit is failed.
    """
    return service.accept(
        AcceptCredit(
            user_id=body.user_id,
            amount=body.amount,
            idempotency_key=_idempotency_key(idempotency_key),
        )
    )


def _idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


@router.get(
    "/{task_id}",
    response_model=CreditView,
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorView}},
)
def get_credit(
    task_id: str,
    service: Annotated[CreditService, Depends(get_credit_service)],
) -> CreditView:
    """Return the credit status for this task id."""
    return service.get_credit(task_id)
