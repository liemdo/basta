from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_credit_service
from app.contracts import MAX_USER_LIST
from app.schemas import ErrorView, UserListView, UserView
from app.services.credits import CreditService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserListView)
def list_users(
    service: Annotated[CreditService, Depends(get_credit_service)],
    limit: Annotated[int, Query(ge=1, le=MAX_USER_LIST)] = MAX_USER_LIST,
) -> UserListView:
    """Return users who already have a balance, most recently updated first."""
    return service.list_users(limit)


@router.get(
    "/{user_id}",
    response_model=UserView,
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorView}},
)
def get_user(
    user_id: str,
    service: Annotated[CreditService, Depends(get_credit_service)],
) -> UserView:
    """Return one user's committed balance."""
    return service.get_user(user_id)
