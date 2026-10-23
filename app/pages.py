"""Demo page. The browser calls the JSON API; this route only serves the built UI."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(tags=["demo"])
DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def _dist_file(relative: str) -> Path:
    root = DIST.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=404)
    return target


@router.get("/")
def demo_page() -> FileResponse:
    """Form to add a credit and a table of committed balances."""
    index = DIST / "index.html"
    if not index.is_file():
        raise HTTPException(
            status_code=503,
            detail="Demo page is not built. From frontend/, run npm ci && npm run build.",
        )
    return FileResponse(index)


@router.get("/{asset_path:path}")
def demo_asset(asset_path: str) -> FileResponse:
    """Built stylesheet, script, and favicon. API routes are registered first."""
    return FileResponse(_dist_file(asset_path))
