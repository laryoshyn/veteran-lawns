"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import get_settings
from database import Base, engine
from routers import auth, dashboard, landscaping, pages, payments, pm_tools, quotes

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

# Rate limiter setup with default limits
# Use memory storage for local development, Redis for production
storage_uri = settings.redis_url if not settings.debug else "memory://"
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=storage_uri,
    default_limits=["200/day", "50/hour"],  # Global default limits
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    # Startup
    logger.info("Starting application...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")
    yield
    # Shutdown
    logger.info("Shutting down application...")
    await engine.dispose()


app = FastAPI(
    title="Veteran Lawns & Landscapes",
    description="Lawn care estimation and quote management",
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Trusted hosts middleware (prevent host header attacks)
if not settings.debug:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["veteranlawnsandlandscapes.com", "www.veteranlawnsandlandscapes.com"],
    )

# CORS middleware (configure for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else ["https://veteranlawnsandlandscapes.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)

    # Prevent MIME type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"

    # Prevent clickjacking
    response.headers["X-Frame-Options"] = "DENY"

    # XSS protection (legacy browsers)
    response.headers["X-XSS-Protection"] = "1; mode=block"

    # Referrer policy
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # Permissions policy (disable unnecessary features)
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

    # Content Security Policy
    if not settings.debug:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://js.stripe.com; "
            "frame-src https://js.stripe.com; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://api.stripe.com; "
            "font-src 'self';"
        )
        # HSTS (HTTP Strict Transport Security)
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )

    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests for monitoring and debugging."""
    # Skip logging for health checks
    if request.url.path == "/health":
        return await call_next(request)

    logger.info(
        f"{request.method} {request.url.path} - "
        f"Client: {request.client.host if request.client else 'unknown'}"
    )
    response = await call_next(request)
    logger.info(f"{request.method} {request.url.path} - Status: {response.status_code}")
    return response


# Mount routers
app.include_router(pages.router, tags=["Pages"])  # HTML pages (no prefix)
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(quotes.router, prefix="/quotes", tags=["Quotes"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(payments.router, prefix="/payments", tags=["Payments"])
app.include_router(landscaping.router, prefix="/landscaping", tags=["Landscaping"])
app.include_router(pm_tools.router, prefix="/pm", tags=["PM Tools"])

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/images", StaticFiles(directory="images"), name="images")
templates = Jinja2Templates(directory="templates")


@app.get("/health")
@limiter.exempt
async def health_check():
    """Health check endpoint for monitoring (exempt from rate limiting)."""
    return {"status": "healthy", "version": "1.0.0"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler to prevent stack trace leakage."""
    logger.exception(f"Unhandled exception on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
