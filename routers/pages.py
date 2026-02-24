"""HTML page routes for the frontend."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with quote form."""
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page."""
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Registration page."""
    return templates.TemplateResponse("register.html", {"request": request})


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """User dashboard page."""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/landscaping", response_class=HTMLResponse)
async def landscaping_page(request: Request):
    """Landscaping services page."""
    return templates.TemplateResponse("landscaping.html", {"request": request})


@router.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Admin dashboard panel (role enforced client-side + API)."""
    return templates.TemplateResponse("admin.html", {"request": request})
