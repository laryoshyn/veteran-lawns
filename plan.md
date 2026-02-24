# Veteran Lawns & Landscapes - Implementation Plan

## Overview

Rebuild the lawn care estimation tool with a modern, secure tech stack emphasizing security, simple maintenance, and common standards.

---

## Tech Stack Decision

| Component | Technology | Justification |
|-----------|------------|---------------|
| Framework | **FastAPI** | Built-in Pydantic validation, OAuth2/JWT, auto-documentation |
| Database | **PostgreSQL 15+** | Proper concurrency, row-level security, production-ready |
| Auth | **FastAPI OAuth2 + JWT** | Modern standard, stateless, secure |
| Password | **Argon2** (via passlib) | OWASP recommended, strongest option |
| Rate Limit | **slowapi** | Redis-backed, distributed limiting |
| Server | **Gunicorn + Uvicorn** | ASGI support for async |
| Reverse Proxy | **Nginx** | SSL termination, static files, security |
| Hosting | **GoDaddy VPS** | Full control, PostgreSQL/Redis support |
| Payments | **Stripe Checkout** | PCI compliant, subscription support |

---

## Critical Gaps Being Fixed

1. Admin dashboard has NO authentication - anyone can access `/dashboard`
2. No role-based access control - no distinction between customer vs admin
3. Stripe payment integration - mentioned but NOT implemented
4. FieldRoutes integration - mentioned but NOT implemented
5. SQLite concurrency issues - not suitable for production
6. Secret key hardcoded - security vulnerability
7. SQL injection vulnerability in Maryland API query construction
8. No rate limiting - vulnerable to brute force attacks
9. No password reset/email verification

---

## Phase 1: Project Setup

### Step 1.1: Create project structure
```
lawn/
├── main.py              # FastAPI app entry point
├── config.py            # Pydantic settings
├── database.py          # PostgreSQL connection
├── models.py            # SQLAlchemy models
├── schemas.py           # Pydantic request/response schemas
├── auth.py              # JWT authentication
├── routers/
│   ├── __init__.py
│   ├── quotes.py        # Quote estimation endpoints
│   ├── payments.py      # Stripe integration
│   ├── dashboard.py     # Customer/admin dashboards
│   └── auth.py          # Login/register/logout
├── services/
│   ├── __init__.py
│   ├── maryland_api.py  # Property data API client
│   ├── stripe_service.py # Stripe Checkout
│   └── fieldroutes.py   # FieldRoutes API client
├── templates/           # Jinja2 HTML templates
├── static/              # CSS, JS
├── requirements.txt
├── .env.example
└── .gitignore
```

### Step 1.2: Create requirements.txt
```
# Core
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
gunicorn>=21.2.0

# Database
sqlalchemy>=2.0.0
asyncpg>=0.29.0
alembic>=1.13.0

# Authentication
python-jose[cryptography]>=3.3.0
passlib[argon2]>=1.7.4

# Validation & Forms
pydantic>=2.5.0
pydantic-settings>=2.1.0
python-multipart>=0.0.6
email-validator>=2.1.0

# Security
slowapi>=0.1.9
secure>=0.3.0

# External APIs
httpx>=0.26.0
stripe>=7.0.0

# Templates
jinja2>=3.1.0

# Utilities
python-dotenv>=1.0.0

# Development
pytest>=7.4.0
pytest-asyncio>=0.23.0
```

### Step 1.3: Create .env.example
```bash
# Application
SECRET_KEY=your-256-bit-random-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=120

# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/lawncare

# Redis (for rate limiting)
REDIS_URL=redis://localhost:6379

# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# FieldRoutes (when available)
FIELDROUTES_API_KEY=
FIELDROUTES_ACCOUNT_ID=
```

---

## Phase 2: Database Setup

### Step 2.1: Create config.py
```python
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 120

    database_url: str
    redis_url: str = "redis://localhost:6379"

    stripe_secret_key: str
    stripe_webhook_secret: str

    fieldroutes_api_key: str = ""
    fieldroutes_account_id: str = ""

    class Config:
        env_file = ".env"

@lru_cache
def get_settings():
    return Settings()
```

### Step 2.2: Create database.py
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

### Step 2.3: Create models.py
```python
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="customer")  # "customer" or "admin"
    is_active = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True))

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    name = Column(String(255), nullable=False)
    address = Column(String(500), nullable=False)
    phone = Column(String(20), nullable=False)
    claimed_size = Column(Float)
    actual_size = Column(Float)
    quote = Column(Float)
    parcel_id = Column(String(50))  # Maryland API ACCTID
    purchased = Column(Boolean, default=False)
    stripe_payment_id = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

---

## Phase 3: Authentication

### Step 3.1: Create auth.py
```python
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Fetch user from database
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exception
    return user

def require_role(required_role: str):
    async def role_checker(current_user = Depends(get_current_user)):
        if current_user.role != required_role:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return role_checker
```

---

## Phase 4: Core Routes

### Step 4.1: Create main.py
```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from secure import SecureHeaders

from routers import auth, quotes, payments, dashboard
from database import engine, Base
from config import get_settings

settings = get_settings()
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
secure_headers = SecureHeaders()

app = FastAPI(title="Veteran Lawns & Landscapes", docs_url="/docs" if settings.debug else None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security headers middleware
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    secure_headers.framework.fastapi(response)
    return response

# Mount routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(quotes.router, prefix="/quotes", tags=["quotes"])
app.include_router(payments.router, prefix="/payments", tags=["payments"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

### Step 4.2: Create routers/quotes.py
```python
from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from schemas import QuoteRequest, QuoteResponse
from services.maryland_api import fetch_actual_size
from auth import get_current_user
from models import Customer

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

PRICE_PER_ACRE = 430  # $215 per 0.5 acres = $430 per acre

@router.post("/estimate", response_model=QuoteResponse)
@limiter.limit("10/minute")
async def create_estimate(
    request: Request,
    quote_request: QuoteRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)  # Optional: allow anonymous
):
    # Fetch actual size from Maryland API
    actual_size = await fetch_actual_size(
        quote_request.street_address,
        quote_request.city,
        quote_request.zipcode
    )

    # Fall back to claimed size if API fails
    if actual_size is None:
        actual_size = quote_request.claimed_size

    # Calculate quote
    quote_amount = round(PRICE_PER_ACRE * actual_size, 2)

    # Store customer record
    customer = Customer(
        user_id=current_user.id if current_user else None,
        name=quote_request.name,
        address=f"{quote_request.street_address}, {quote_request.city}, {quote_request.zipcode}",
        phone=quote_request.phone,
        claimed_size=quote_request.claimed_size,
        actual_size=actual_size,
        quote=quote_amount
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)

    return QuoteResponse(
        customer_id=customer.id,
        claimed_size=quote_request.claimed_size,
        actual_size=actual_size,
        monthly_quote=quote_amount
    )
```

### Step 4.3: Create routers/dashboard.py
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import Customer, User
from auth import get_current_user, require_role

router = APIRouter()

@router.get("/my-quotes")
async def customer_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Customer sees only their own quotes."""
    result = await db.execute(
        select(Customer).where(Customer.user_id == current_user.id).order_by(Customer.created_at.desc())
    )
    return result.scalars().all()

@router.get("/admin")
async def admin_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """Admin sees all customer quotes."""
    result = await db.execute(
        select(Customer).order_by(Customer.created_at.desc())
    )
    return result.scalars().all()
```

---

## Phase 5: Stripe Integration

### Step 5.1: Create routers/payments.py
```python
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
import stripe

from database import get_db
from models import Customer, User
from auth import get_current_user
from config import get_settings

settings = get_settings()
stripe.api_key = settings.stripe_secret_key

router = APIRouter()

@router.post("/create-checkout/{customer_id}")
async def create_checkout_session(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    customer = await db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Quote not found")

    # Verify ownership
    if customer.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Create Stripe Checkout Session
    checkout_session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"Monthly Lawn Care - {customer.actual_size:.2f} acres",
                    "description": f"Weekly mowing service for {customer.address}",
                },
                "unit_amount": int(customer.quote * 100),  # Stripe uses cents
                "recurring": {"interval": "month"},
            },
            "quantity": 1,
        }],
        mode="subscription",
        success_url="https://yourdomain.com/payment/success?session_id={CHECKOUT_SESSION_ID}",
        cancel_url="https://yourdomain.com/payment/cancel",
        metadata={
            "customer_id": str(customer_id),
            "user_id": str(current_user.id)
        }
    )

    return {"checkout_url": checkout_session.url}

@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_id = int(session["metadata"]["customer_id"])

        customer = await db.get(Customer, customer_id)
        if customer:
            customer.purchased = True
            customer.stripe_payment_id = session["id"]
            await db.commit()

    return {"status": "success"}
```

---

## Phase 6: Security Hardening

### Step 6.1: Input validation schemas (schemas.py)
```python
from pydantic import BaseModel, Field, EmailStr, field_validator
import re

class QuoteRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    street_address: str = Field(..., min_length=5, max_length=200)
    city: str = Field(..., min_length=2, max_length=100)
    zipcode: str = Field(..., pattern=r"^\d{5}(-\d{4})?$")
    phone: str = Field(..., min_length=10, max_length=20)
    claimed_size: float = Field(..., gt=0, le=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not re.match(r"^[A-Za-z\s\-\.]+$", v):
            raise ValueError("Name contains invalid characters")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        if not re.match(r"^[\d\-\+\(\)\s]+$", v):
            raise ValueError("Invalid phone format")
        return v

class QuoteResponse(BaseModel):
    customer_id: int
    claimed_size: float
    actual_size: float
    monthly_quote: float

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
```

### Step 6.2: Rate limiting configuration
```python
# In main.py - already included above
# Login: 5 attempts per minute
# Quote requests: 10 per minute
# Global: 200 requests per day per IP
```

---

## Phase 7: Deployment

### Step 7.1: Nginx configuration
```nginx
server {
    listen 443 ssl http2;
    server_name veteranlawnsandlandscapes.com;

    ssl_certificate /etc/letsencrypt/live/veteranlawnsandlandscapes.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/veteranlawnsandlandscapes.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /var/www/lawn/static;
        expires 30d;
    }
}

server {
    listen 80;
    server_name veteranlawnsandlandscapes.com;
    return 301 https://$server_name$request_uri;
}
```

### Step 7.2: Systemd service
```ini
# /etc/systemd/system/lawncare.service
[Unit]
Description=Veteran Lawns FastAPI App
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/lawn
Environment="PATH=/var/www/lawn/venv/bin"
EnvironmentFile=/var/www/lawn/.env
ExecStart=/var/www/lawn/venv/bin/gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000
Restart=always

[Install]
WantedBy=multi-user.target
```

### Step 7.3: Deployment commands
```bash
# On VPS
sudo apt update && sudo apt install -y python3.12 python3.12-venv postgresql nginx redis-server

# Create database
sudo -u postgres createdb lawncare
sudo -u postgres createuser lawnuser -P

# Setup application
cd /var/www
git clone <repo> lawn
cd lawn
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with production values

# SSL certificate
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d veteranlawnsandlandscapes.com

# Start services
sudo systemctl enable --now lawncare
sudo systemctl enable --now nginx
```

---

## Verification Checklist

- [ ] Admin routes require `admin` role (test: access `/dashboard/admin` as customer → 403)
- [ ] Customer dashboard shows only own records (test: User A cannot see User B's quotes)
- [ ] Rate limiting blocks rapid login attempts (test: 6 logins in 1 minute → 429)
- [ ] Stripe test payment completes successfully
- [ ] Webhook updates `purchased` flag
- [ ] HTTPS redirects work
- [ ] Security headers present (check with securityheaders.com)
- [ ] Password reset flow works
- [ ] Maryland API fallback works when API is down

---

## Summary

**Changed from original:**
- Flask → **FastAPI** (better validation, async, security)
- SQLite → **PostgreSQL** (production concurrency)
- Werkzeug → **Argon2** (stronger password hashing)
- No auth → **OAuth2/JWT** with role-based access
- No payments → **Stripe Checkout** (PCI compliant)
- Hardcoded secrets → **Environment variables**
- No rate limiting → **slowapi with Redis**
