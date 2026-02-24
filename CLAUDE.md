# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Veteran: Lawns & Landscapes estimation tool - a FastAPI web application for lawn care quote generation with secure authentication, Stripe payments, and property validation.

## Technology Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2.0 (async)
- **Database**: PostgreSQL 15+ (asyncpg driver)
- **Authentication**: OAuth2 + JWT tokens, Argon2 password hashing
- **Rate Limiting**: slowapi with Redis backend
- **External APIs**: Maryland Property Data API (Harford County), Stripe Checkout, FieldRoutes
- **Server**: Gunicorn + Uvicorn workers (ASGI)
- **Deployment**: GoDaddy VPS with Nginx reverse proxy

## Project Structure

```
lawn/
├── main.py              # FastAPI app entry point
├── config.py            # Pydantic settings (env vars)
├── database.py          # Async PostgreSQL connection
├── models.py            # SQLAlchemy ORM models
├── schemas.py           # Pydantic request/response schemas
├── auth.py              # JWT authentication helpers
├── routers/
│   ├── auth.py          # Login/register/logout
│   ├── quotes.py        # Quote estimation endpoints
│   ├── payments.py      # Stripe integration
│   └── dashboard.py     # Customer/admin dashboards
├── services/
│   ├── maryland_api.py  # Property data API client
│   ├── stripe_service.py
│   └── fieldroutes.py
├── templates/           # Jinja2 HTML templates
├── static/              # CSS, JS assets
├── requirements.txt
├── .env.example
└── .gitignore
```

## Development Commands

```bash
# Setup virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your values

# Run development server
uvicorn main:app --reload --port 8000

# Run tests
pytest

# Production
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000
```

## Key Architecture

### Database Schema

- **users**: id, email, hashed_password, role (customer/admin), is_active, email_verified, created_at, last_login
- **customers**: id, user_id (FK), name, address, phone, claimed_size, actual_size, quote, parcel_id, purchased, stripe_payment_id, created_at

### Pricing Model

Linear scaling at $430/acre ($215 for 0.5 acres).

### Property Validation

Uses Maryland GeoData API to validate customer-claimed lawn sizes:
```
https://mdgeodata.md.gov/imap/rest/services/PlanningCadastre/MD_PropertyData/MapServer/0/query
```
Filter: `JURSCODE = 'HARF'` (Harford County)

### API Routes

- `POST /auth/register` - User registration
- `POST /auth/login` - JWT token issuance
- `POST /quotes/estimate` - Create quote (rate limited: 10/min)
- `GET /dashboard/my-quotes` - Customer's own quotes
- `GET /dashboard/admin` - All quotes (admin role required)
- `POST /payments/create-checkout/{id}` - Stripe Checkout session
- `POST /payments/webhook` - Stripe webhook handler

## Security Requirements

- All secrets via environment variables (never hardcoded)
- Passwords hashed with Argon2 (OWASP recommended)
- JWT tokens with configurable expiration
- Role-based access control (customer vs admin)
- Rate limiting on authentication and quote endpoints
- HTTPS required in production (Nginx SSL termination)
- Stripe webhook signature verification

---

## Small Business Coding Practices

Follow these principles to keep the codebase maintainable, secure, and cost-effective.

### 1. Keep It Simple

- **YAGNI** (You Aren't Gonna Need It): Don't build features until they're needed
- **One way to do things**: Avoid multiple patterns for the same task
- **Flat is better than nested**: Minimize abstraction layers
- **Comments explain "why", code explains "what"**

### 2. Security First

- **Never commit secrets**: Use `.env` files and `.gitignore`
- **Validate all input**: Use Pydantic schemas for every endpoint
- **Parameterized queries only**: SQLAlchemy handles this - never use f-strings for SQL
- **Rate limit public endpoints**: Prevent abuse and reduce costs
- **Log security events**: Failed logins, permission denials, unusual patterns

### 3. Error Handling

- **Fail gracefully**: External API down? Use fallback values
- **User-friendly errors**: Hide stack traces in production, show helpful messages
- **Log errors with context**: Include request ID, user ID, endpoint
- **Don't swallow exceptions**: Log them even if you handle them

### 4. Database Practices

- **Migrations always**: Use Alembic, never manual schema changes
- **Index foreign keys**: `user_id` columns need indexes
- **Soft delete when needed**: Add `is_deleted` flag instead of DELETE for audit trails
- **Connection pooling**: asyncpg handles this - don't create connections per request

### 5. API Design

- **Consistent responses**: Always return JSON with predictable structure
- **Meaningful HTTP status codes**: 400 for bad input, 401 for auth, 403 for permission, 404 for not found
- **Version your API**: Prefix routes with `/v1/` when breaking changes are possible
- **Document with OpenAPI**: FastAPI generates this automatically at `/docs`

### 6. Testing Strategy

- **Test the critical path**: User registration, login, quote creation, payment
- **Integration over unit**: Test actual database and API interactions
- **Use fixtures**: Consistent test data setup
- **Test error cases**: Invalid input, unauthorized access, missing resources

### 7. Deployment & Operations

- **Environment parity**: Dev, staging, and production should be similar
- **Health checks**: Add `/health` endpoint for monitoring
- **Structured logging**: JSON format for easy parsing
- **Backup strategy**: Daily PostgreSQL backups, test restores quarterly

### 8. Cost Management

- **Cache expensive operations**: Maryland API calls, computed quotes
- **Limit third-party API calls**: Batch where possible, cache results
- **Monitor usage**: Track Stripe fees, API call counts, database size
- **Right-size infrastructure**: Start small, scale when needed

### 9. Code Organization

- **One file, one purpose**: Don't mix auth logic with business logic
- **Dependency injection**: Use FastAPI's `Depends()` for testability
- **Configuration in one place**: All settings in `config.py`
- **Constants are named**: `PRICE_PER_ACRE = 430` not magic numbers

### 10. Documentation

- **README for setup**: New developer should be running in 15 minutes
- **CLAUDE.md for AI assistance**: Keep this file updated
- **Inline docs for complex logic**: Pricing calculations, API integrations
- **API docs auto-generated**: FastAPI's `/docs` endpoint
