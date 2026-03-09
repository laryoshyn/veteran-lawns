"""Dashboard endpoints for customers and admins."""

import logging
import time
from datetime import date, timedelta
from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, get_password_hash, require_admin, require_staff, verify_password
from config import get_settings
from database import get_db
from models import Customer, User
from schemas import CustomerResponse
from services.email import send_payment_link_email
from services.pricing import load_rates_raw, save_rates
from services.settings import load_business_settings, save_business_settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/my-quotes", response_model=list[CustomerResponse])
async def get_my_quotes(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[Customer]:
    """
    Get all quotes for the current authenticated user.

    Returns only quotes belonging to the logged-in user.
    """
    result = await db.execute(
        select(Customer)
        .where(Customer.user_id == current_user.id)
        .order_by(Customer.created_at.desc())
    )
    quotes = result.scalars().all()
    logger.info(f"User {current_user.email} fetched {len(quotes)} quotes")
    return list(quotes)


@router.get("/my-quotes/{quote_id}", response_model=CustomerResponse)
async def get_my_quote(
    quote_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Customer:
    """
    Get a specific quote by ID for the current user.

    Returns 404 if not found or not owned by user.
    """
    result = await db.execute(
        select(Customer).where(
            Customer.id == quote_id,
            Customer.user_id == current_user.id,
        )
    )
    quote = result.scalar_one_or_none()

    if not quote:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quote not found",
        )

    return quote


# --- Admin Endpoints ---


@router.get("/admin/quotes", response_model=list[CustomerResponse])
async def admin_get_all_quotes(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_staff)],
    skip: int = 0,
    limit: int = 100,
) -> list[Customer]:
    """
    Get all customer quotes (admin only).

    Supports pagination via skip and limit parameters.
    """
    result = await db.execute(
        select(Customer)
        .order_by(Customer.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    quotes = result.scalars().all()
    logger.info(f"Admin {current_user.email} fetched {len(quotes)} quotes")
    return list(quotes)


@router.get("/admin/quotes/{quote_id}", response_model=CustomerResponse)
async def admin_get_quote(
    quote_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_staff)],
) -> Customer:
    """
    Get a specific quote by ID (admin only).
    """
    result = await db.execute(select(Customer).where(Customer.id == quote_id))
    quote = result.scalar_one_or_none()

    if not quote:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quote not found",
        )

    return quote


@router.post("/admin/quotes/{quote_id}/approve")
async def admin_approve_quote(
    quote_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_staff)],
):
    """Mark a quote as approved (admin or sales). Required before sending a payment link."""
    result = await db.execute(select(Customer).where(Customer.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")
    if quote.purchased:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote already purchased")

    quote.quote_approved = True
    await db.commit()
    logger.info(f"Quote {quote_id} approved by {current_user.email}")
    return {"message": "Quote approved"}


@router.post("/admin/quotes/{quote_id}/send-payment-link")
async def admin_send_payment_link(
    quote_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_staff)],
):
    """Create a Stripe checkout URL and email it to the customer."""
    result = await db.execute(select(Customer).where(Customer.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")
    if quote.purchased:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote already purchased")
    if not quote.quote_approved:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote must be approved before sending payment link")
    if not quote.quote or quote.quote <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote has no valid amount")

    _settings = get_settings()
    stripe.api_key = _settings.stripe_secret_key
    base = "http://localhost:8000" if _settings.debug else "https://veteranlawnsandlandscapes.com"

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"Monthly Lawn Care - {quote.actual_size:.2f} acres",
                        "description": f"Service for {quote.address}",
                    },
                    "unit_amount": int(quote.quote * 100),
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            mode="subscription",
            success_url=f"{base}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/payment/cancel",
            customer_email=quote.email,
            expires_at=int(time.time()) + 86400,
            metadata={"customer_id": str(quote.id), "quote_amount": str(quote.quote)},
        )
        checkout_url = session.url
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating checkout for quote {quote_id}: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Payment service error")

    sent = await send_payment_link_email(
        to_email=quote.email,
        customer_name=quote.name,
        checkout_url=checkout_url,
        monthly_quote=quote.quote,
    )

    logger.info(
        f"Payment link for quote {quote_id} created by {current_user.email}, "
        f"email_sent={sent}, url={checkout_url}"
    )
    return {"checkout_url": checkout_url, "email_sent": sent}


@router.get("/admin/stats")
async def admin_get_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
):
    """
    Get dashboard statistics (admin only).

    Returns counts and aggregations for business metrics.
    """
    # Total quotes
    total_quotes = await db.scalar(select(func.count(Customer.id)))

    # Purchased quotes
    purchased_quotes = await db.scalar(
        select(func.count(Customer.id)).where(Customer.purchased == True)  # noqa: E712
    )

    # Total revenue (from purchased quotes)
    total_revenue = await db.scalar(
        select(func.sum(Customer.quote)).where(Customer.purchased == True)  # noqa: E712
    )

    # Average quote value
    avg_quote = await db.scalar(select(func.avg(Customer.quote)))

    # Total users
    total_users = await db.scalar(select(func.count(User.id)))

    return {
        "total_quotes": total_quotes or 0,
        "purchased_quotes": purchased_quotes or 0,
        "conversion_rate": (
            round((purchased_quotes or 0) / total_quotes * 100, 1)
            if total_quotes
            else 0
        ),
        "total_revenue": round(total_revenue or 0, 2),
        "average_quote": round(avg_quote or 0, 2),
        "total_users": total_users or 0,
    }


# --- Calendar Endpoints ---


def _generate_service_dates(
    start_date: date,
    frequency: str,
    end_date: date,
) -> list[date]:
    """Generate service dates based on frequency within a date range."""
    dates = []
    current = start_date

    # Map frequency to days between services
    frequency_days = {
        "weekly": 7,
        "biweekly": 14,
        "monthly": 30,
    }
    interval = frequency_days.get(frequency, 7)

    while current <= end_date:
        if current >= start_date:
            dates.append(current)
        current += timedelta(days=interval)

    return dates


@router.get("/my-calendar")
async def get_my_calendar(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    year: int | None = None,
    month: int | None = None,
):
    """
    Get calendar events for the current user's scheduled services.

    Returns service dates for the specified month (defaults to current month).
    """
    today = date.today()
    year = year or today.year
    month = month or today.month

    # Calculate month boundaries
    first_day = date(year, month, 1)
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)

    # Get user's active services
    result = await db.execute(
        select(Customer).where(
            Customer.user_id == current_user.id,
            Customer.purchased == True,  # noqa: E712
            Customer.service_status.in_(["active", "pending"]),
            Customer.service_start_date.isnot(None),
        )
    )
    services = result.scalars().all()

    events = []
    for service in services:
        # Generate service dates for this month
        service_dates = _generate_service_dates(
            service.service_start_date,
            service.service_frequency or "weekly",
            last_day,
        )

        for svc_date in service_dates:
            if first_day <= svc_date <= last_day:
                events.append({
                    "id": service.id,
                    "date": svc_date.isoformat(),
                    "title": "Lawn Service",
                    "address": service.address,
                    "type": "service",
                    "status": service.service_status,
                })

    return {
        "year": year,
        "month": month,
        "events": sorted(events, key=lambda x: x["date"]),
    }


@router.get("/admin/calendar")
async def admin_get_calendar(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    year: int | None = None,
    month: int | None = None,
):
    """
    Get calendar events for all scheduled services (admin only).

    Returns all service dates and availability info for the specified month.
    """
    today = date.today()
    year = year or today.year
    month = month or today.month

    # Calculate month boundaries
    first_day = date(year, month, 1)
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)

    # Get all active services
    result = await db.execute(
        select(Customer).where(
            Customer.purchased == True,  # noqa: E712
            Customer.service_status.in_(["active", "pending"]),
            Customer.service_start_date.isnot(None),
        )
    )
    services = result.scalars().all()

    events = []
    daily_counts = {}

    for service in services:
        service_dates = _generate_service_dates(
            service.service_start_date,
            service.service_frequency or "weekly",
            last_day,
        )

        for svc_date in service_dates:
            if first_day <= svc_date <= last_day:
                date_str = svc_date.isoformat()
                events.append({
                    "id": service.id,
                    "date": date_str,
                    "title": service.name,
                    "address": service.address,
                    "size": service.actual_size,
                    "type": "service",
                    "status": service.service_status,
                    "frequency": service.service_frequency,
                })

                # Track daily counts for capacity
                daily_counts[date_str] = daily_counts.get(date_str, 0) + 1

    # Calculate availability (assume max 8 services per day)
    max_daily_capacity = 8
    availability = {}
    current = first_day
    while current <= last_day:
        date_str = current.isoformat()
        count = daily_counts.get(date_str, 0)
        availability[date_str] = {
            "scheduled": count,
            "available": max(0, max_daily_capacity - count),
            "capacity": max_daily_capacity,
            "status": "full" if count >= max_daily_capacity else "available",
        }
        current += timedelta(days=1)

    return {
        "year": year,
        "month": month,
        "events": sorted(events, key=lambda x: x["date"]),
        "availability": availability,
        "total_services": len(services),
    }


# --- User Management Endpoints (Admin) ---


@router.get("/admin/users")
async def admin_get_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
    skip: int = 0,
    limit: int = 100,
    role: str | None = None,
    is_active: bool | None = None,
):
    """
    Get all users with optional filtering (admin only).
    """
    query = select(User).order_by(User.created_at.desc())

    if role:
        query = query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    users = result.scalars().all()

    logger.info(f"Admin {current_user.email} fetched {len(users)} users")

    return [
        {
            "id": u.id,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "email_verified": u.email_verified,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None,
        }
        for u in users
    ]


@router.get("/admin/users/{user_id}")
async def admin_get_user(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    """
    Get a specific user by ID (admin only).
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Get user's quotes count
    quotes_result = await db.execute(
        select(func.count(Customer.id)).where(Customer.user_id == user_id)
    )
    quotes_count = quotes_result.scalar() or 0

    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "email_verified": user.email_verified,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "quotes_count": quotes_count,
    }


@router.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
    role: str | None = None,
    is_active: bool | None = None,
):
    """
    Update a user's role or active status (admin only).
    """
    # Prevent self-modification of role
    if user_id == current_user.id and role is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Validate role if provided
    if role is not None:
        if role not in ["customer", "admin", "pm", "sales"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role. Must be: customer, admin, pm, or sales",
            )
        user.role = role
        logger.info(f"Admin {current_user.email} changed user {user.email} role to {role}")

    if is_active is not None:
        user.is_active = is_active
        logger.info(f"Admin {current_user.email} set user {user.email} active={is_active}")

    await db.commit()
    await db.refresh(user)

    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "message": "User updated successfully",
    }


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
):
    """
    Delete a user (admin only). Deactivates instead of hard delete.
    """
    # Prevent self-deletion
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Soft delete - deactivate instead of hard delete
    user.is_active = False
    await db.commit()

    logger.info(f"Admin {current_user.email} deactivated user {user.email}")

    return {"message": f"User {user.email} has been deactivated"}


# --- Customer Management Endpoints (Admin) ---


@router.get("/admin/customers")
async def admin_get_customers(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    skip: int = 0,
    limit: int = 100,
    purchased: bool | None = None,
    service_status: str | None = None,
):
    """
    Get all customers with optional filtering (admin only).
    """
    query = select(Customer).order_by(Customer.created_at.desc())

    if purchased is not None:
        query = query.where(Customer.purchased == purchased)
    if service_status:
        query = query.where(Customer.service_status == service_status)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    customers = result.scalars().all()

    return [
        {
            "id": c.id,
            "name": c.name,
            "email": c.user.email if c.user else None,
            "address": c.address,
            "phone": c.phone,
            "claimed_size": c.claimed_size,
            "actual_size": c.actual_size,
            "quote": c.quote,
            "purchased": c.purchased,
            "service_start_date": c.service_start_date.isoformat() if c.service_start_date else None,
            "service_frequency": c.service_frequency,
            "service_status": c.service_status,
            "stripe_payment_id": c.stripe_payment_id,
            "fieldroutes_customer_id": c.fieldroutes_customer_id,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in customers
    ]


@router.get("/admin/customers/{customer_id}")
async def admin_get_customer(
    customer_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    """
    Get a specific customer by ID (admin only).
    """
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )

    return {
        "id": customer.id,
        "user_id": customer.user_id,
        "name": customer.name,
        "email": customer.user.email if customer.user else None,
        "address": customer.address,
        "phone": customer.phone,
        "claimed_size": customer.claimed_size,
        "actual_size": customer.actual_size,
        "quote": customer.quote,
        "parcel_id": customer.parcel_id,
        "purchased": customer.purchased,
        "stripe_payment_id": customer.stripe_payment_id,
        "service_start_date": customer.service_start_date.isoformat() if customer.service_start_date else None,
        "service_frequency": customer.service_frequency,
        "service_status": customer.service_status,
        "fieldroutes_customer_id": customer.fieldroutes_customer_id,
        "fieldroutes_subscription_id": customer.fieldroutes_subscription_id,
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
    }


@router.patch("/admin/customers/{customer_id}")
async def admin_update_customer(
    customer_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    address: str | None = None,
    claimed_size: float | None = None,
    actual_size: float | None = None,
    quote: float | None = None,
    service_status: str | None = None,
    service_frequency: str | None = None,
    service_start_date: str | None = None,
):
    """
    Update a customer's details (admin only).
    """
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )

    # Update fields if provided
    if name is not None:
        customer.name = name
    if email is not None:
        customer.email = email
    if phone is not None:
        customer.phone = phone
    if address is not None:
        customer.address = address
    if claimed_size is not None:
        customer.claimed_size = claimed_size
    if actual_size is not None:
        customer.actual_size = actual_size
        # Recalculate quote based on new size ($430/acre)
        customer.quote = round(actual_size * 430, 2)
    if quote is not None:
        customer.quote = quote
    if service_start_date is not None:
        try:
            customer.service_start_date = date.fromisoformat(service_start_date)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Use YYYY-MM-DD",
            )
    if service_status is not None:
        valid_statuses = ["pending", "active", "paused", "cancelled"]
        if service_status not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be: {', '.join(valid_statuses)}",
            )
        customer.service_status = service_status
    if service_frequency is not None:
        valid_frequencies = ["weekly", "biweekly", "monthly"]
        if service_frequency not in valid_frequencies:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid frequency. Must be: {', '.join(valid_frequencies)}",
            )
        customer.service_frequency = service_frequency

    await db.commit()
    await db.refresh(customer)

    logger.info(f"Admin {current_user.email} updated customer {customer.id}")

    return {
        "id": customer.id,
        "name": customer.name,
        "address": customer.address,
        "quote": customer.quote,
        "service_status": customer.service_status,
        "message": "Customer updated successfully",
    }


@router.delete("/admin/customers/{customer_id}")
async def admin_delete_customer(
    customer_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
):
    """
    Delete a customer record (admin only).
    For purchased customers, cancels service instead of deleting.
    """
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )

    if customer.purchased:
        # For purchased customers, just cancel the service
        customer.service_status = "cancelled"
        await db.commit()
        logger.info(f"Admin {current_user.email} cancelled service for customer {customer.id}")
        return {"message": f"Service cancelled for {customer.name}"}
    else:
        # For unpurchased quotes, can delete
        await db.delete(customer)
        await db.commit()
        logger.info(f"Admin {current_user.email} deleted customer {customer.id}")
        return {"message": f"Customer record deleted"}


# --- Pricing Management Endpoints (Admin) ---


@router.get("/admin/rates")
async def admin_get_rates(
    _: Annotated[User, Depends(require_admin)],
):
    """Get current pricing tiers (admin only)."""
    return load_rates_raw()


@router.put("/admin/rates")
async def admin_update_rates(
    rates: dict,
    current_user: Annotated[User, Depends(require_admin)],
):
    """
    Replace pricing tiers (admin only).

    Expects the full rates object matching rates.json structure.
    Each tier must have: label, min_acres, max_acres (or null), price (or null),
    quote_required.
    """
    tiers = rates.get("tiers", [])
    if not tiers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one pricing tier is required",
        )

    for i, tier in enumerate(tiers):
        for field in ("label", "min_acres", "quote_required"):
            if field not in tier:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Tier {i + 1} missing required field: {field}",
                )
        if not tier["quote_required"] and tier.get("price") is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tier '{tier['label']}' must have a price when quote_required is false",
            )

    save_rates(rates)
    logger.info(f"Admin {current_user.email} updated pricing rates")
    return {"message": "Pricing rates updated", "tiers": len(tiers)}


@router.get("/admin/db-schema")
async def admin_db_schema(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return database table structure for the admin schema viewer."""
    tables = []
    # Get all table names from sqlite_master
    result = await db.execute(
        __import__("sqlalchemy").text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    )
    table_names = [row[0] for row in result.fetchall()]

    for table_name in table_names:
        col_result = await db.execute(
            __import__("sqlalchemy").text(f"PRAGMA table_info('{table_name}')")
        )
        columns = [
            {
                "cid": row[0],
                "name": row[1],
                "type": row[2],
                "not_null": bool(row[3]),
                "default": row[4],
                "pk": bool(row[5]),
            }
            for row in col_result.fetchall()
        ]

        idx_result = await db.execute(
            __import__("sqlalchemy").text(f"PRAGMA index_list('{table_name}')")
        )
        indexes = [{"name": row[1], "unique": bool(row[2])} for row in idx_result.fetchall()]

        # Row count
        count_result = await db.execute(
            __import__("sqlalchemy").text(f"SELECT COUNT(*) FROM '{table_name}'")
        )
        row_count = count_result.scalar()

        tables.append({
            "name": table_name,
            "columns": columns,
            "indexes": indexes,
            "row_count": row_count,
        })

    return {"tables": tables}


@router.get("/admin/settings")
async def admin_get_settings(
    _: Annotated[User, Depends(require_admin)],
):
    """Return full settings for the admin settings panel."""
    s = get_settings()
    biz = load_business_settings()
    return {
        "business": biz,
        "integrations": {
            "stripe": {
                "configured": bool(s.stripe_secret_key),
                "secret_key": s.stripe_secret_key,
                "webhook_secret": s.stripe_webhook_secret,
            },
            "fieldroutes": {
                "configured": bool(s.fieldroutes_api_key and s.fieldroutes_account_id),
                "api_key": s.fieldroutes_api_key,
                "account_id": s.fieldroutes_account_id,
                "api_url": s.fieldroutes_api_url,
            },
            "smtp": {
                "configured": bool(s.smtp_host and s.smtp_user and s.smtp_password),
                "host": s.smtp_host,
                "port": s.smtp_port,
                "user": s.smtp_user,
                "password": s.smtp_password,
                "from_address": s.smtp_from,
            },
            "mta": {
                "configured": bool(s.mta_api_key and s.mta_account_id),
                "api_key": s.mta_api_key,
                "account_id": s.mta_account_id,
            },
            "zillow": {
                "configured": bool(s.zillow_api_key),
                "api_key": s.zillow_api_key,
                "api_host": s.zillow_api_host,
            },
            "everify": {
                "configured": bool(s.everify_client_id and s.everify_client_secret and s.everify_company_id),
                "client_id": s.everify_client_id,
                "client_secret": s.everify_client_secret,
                "company_id": s.everify_company_id,
                "api_url": s.everify_api_url,
            },
            "paychex": {
                "configured": bool(s.paychex_client_id and s.paychex_client_secret and s.paychex_company_id),
                "client_id": s.paychex_client_id,
                "client_secret": s.paychex_client_secret,
                "company_id": s.paychex_company_id,
                "api_url": s.paychex_api_url,
            },
        },
        "app": {
            "token_expire_minutes": s.access_token_expire_minutes,
            "price_per_acre": s.price_per_acre,
        },
    }


@router.put("/admin/settings")
async def admin_update_settings(
    data: dict,
    current_user: Annotated[User, Depends(require_admin)],
):
    """Save editable business settings (admin only)."""
    save_business_settings(data)
    logger.info(f"Admin {current_user.email} updated business settings")
    return {"message": "Settings saved"}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class QuoteEditRequest(BaseModel):
    actual_size: float | None = None
    map_property_size: float | None = None
    quote: float | None = None


def _get_base_url() -> str:
    """Get the base URL for redirects."""
    _settings = get_settings()
    if _settings.debug:
        return "http://localhost:8000"
    return "https://veteranlawnsandlandscapes.com"


@router.post("/admin/change-password")
async def admin_change_password(
    body: ChangePasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
):
    """Change the current admin's password."""
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 8 characters")
    current_user.hashed_password = get_password_hash(body.new_password)
    await db.commit()
    logger.info(f"Admin {current_user.email} changed their password")
    return {"message": "Password updated successfully"}


@router.patch("/admin/quotes/{quote_id}")
async def admin_edit_quote(
    quote_id: int,
    data: QuoteEditRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_staff)],
):
    """Edit quote fields (actual_size, map_property_size, quote amount)."""
    result = await db.execute(select(Customer).where(Customer.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")
    if data.actual_size is not None:
        quote.actual_size = data.actual_size
    if data.map_property_size is not None:
        quote.map_property_size = data.map_property_size
    if data.quote is not None:
        quote.quote = data.quote
    await db.commit()
    logger.info(f"Staff {current_user.email} edited quote {quote_id}")
    return {"message": "Quote updated"}


@router.post("/admin/quotes/{quote_id}/approve-and-send")
async def admin_approve_and_send(
    quote_id: int,
    data: QuoteEditRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_staff)],
):
    """Edit quote fields, approve, create Stripe checkout, and email payment link."""
    result = await db.execute(select(Customer).where(Customer.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")
    if quote.purchased:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote already purchased")

    # Apply edits
    if data.actual_size is not None:
        quote.actual_size = data.actual_size
    if data.map_property_size is not None:
        quote.map_property_size = data.map_property_size
    if data.quote is not None:
        quote.quote = data.quote

    if not quote.quote or quote.quote <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote amount must be greater than zero")

    quote.quote_approved = True
    await db.commit()
    await db.refresh(quote)

    _settings = get_settings()
    stripe.api_key = _settings.stripe_secret_key

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"Monthly Lawn Care - {quote.actual_size:.2f} acres",
                        "description": f"Weekly mowing service for {quote.address}",
                    },
                    "unit_amount": int(quote.quote * 100),
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            mode="subscription",
            success_url=f"{_get_base_url()}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{_get_base_url()}/payment/cancel",
            customer_email=quote.email,
            expires_at=int(time.time()) + 86400,
            metadata={"customer_id": str(quote_id), "quote_amount": str(quote.quote)},
        )
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error for quote {quote_id}: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Payment service error")

    email_sent = await send_payment_link_email(
        to_email=quote.email,
        customer_name=quote.name,
        checkout_url=checkout_session.url,
        monthly_quote=quote.quote,
    )
    logger.info(f"Staff {current_user.email} approved+sent quote {quote_id}, email_sent={email_sent}")
    return {"checkout_url": checkout_session.url, "email_sent": email_sent}
