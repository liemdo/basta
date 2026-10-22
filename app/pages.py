"""Demo page. The browser calls the JSON API; this route only renders HTML."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["demo"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


@router.get("/")
def demo_page(request: Request):
    """Form to add a credit and a table of committed balances."""
    return templates.TemplateResponse(request, "index.html")
