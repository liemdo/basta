from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import get_health_service
from app.schemas import HealthView
from app.services.health import HealthService
from app.statuses import DependencyStatus

router = APIRouter(tags=["health"])


def health_http_status(report: HealthView) -> int:
    """200 when MongoDB and Redis both answer. 503 when either does not."""
    if report.mongodb == DependencyStatus.UP and report.redis == DependencyStatus.UP:
        return status.HTTP_200_OK
    return status.HTTP_503_SERVICE_UNAVAILABLE


@router.get(
    "/health",
    response_model=HealthView,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthView}},
)
def health(
    response: Response,
    service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthView:
    """Report MongoDB and Redis. A down dependency is 503."""
    report = service.check()
    response.status_code = health_http_status(report)
    return report
