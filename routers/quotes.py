"""Quote estimation endpoints."""

import logging
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from config import get_settings
from database import get_db
from models import Customer, User
from schemas import (
    CustomerWithServiceResponse,
    QuoteRequest,
    QuoteResponse,
    ServiceScheduleResponse,
    ServiceStartRequest,
)
from services.maryland_api import fetch_actual_size
from services.pricing import calculate_price, load_rates_raw

logger = logging.getLogger(__name__)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
settings = get_settings()


def get_optional_user_id(authorization: str | None = Header(None)) -> int | None:
    """Extract user ID from token if provided, otherwise return None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None

    try:
        from jose import jwt
        token = authorization.split(" ")[1]
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        user_id_str = payload.get("sub")
        return int(user_id_str) if user_id_str else None
    except Exception:
        return None


@router.post("/estimate", response_model=QuoteResponse)
@limiter.limit("10/minute")
async def create_estimate(
    request: Request,
    quote_request: QuoteRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[int | None, Depends(get_optional_user_id)] = None,
) -> QuoteResponse:
    """
    Create a lawn care quote estimate.

    No registration required - just provide your email.
    Looks up actual property size from Maryland Property Data API
    and calculates monthly service cost.

    Rate limited to 10 requests per minute.
    """
    # Try to fetch actual size from Maryland API
    actual_size, parcel_id = await fetch_actual_size(
        quote_request.street_address,
        quote_request.city,
        quote_request.zipcode,
    )

    # Determine if size was verified via API
    size_verified = actual_size is not None

    # Fall back to claimed size if API lookup failed
    if actual_size is None:
        actual_size = quote_request.claimed_size
        logger.info(
            f"Using claimed size for {quote_request.street_address}: "
            f"{quote_request.claimed_size} acres"
        )

    # Look up price tier for this lot size
    monthly_quote, quote_required, tier_label = calculate_price(actual_size)

    # Build full address string
    full_address = (
        f"{quote_request.street_address}, "
        f"{quote_request.city}, MD {quote_request.zipcode}"
    )

    # Store customer/quote record (quote=0 when a manual quote is required)
    customer = Customer(
        user_id=user_id,
        name=quote_request.name,
        email=quote_request.email,
        address=full_address,
        phone=quote_request.phone,
        claimed_size=quote_request.claimed_size,
        actual_size=actual_size,
        quote=monthly_quote or 0.0,
        parcel_id=parcel_id,
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)

    logger.info(
        f"Quote created: {customer.id} - {quote_request.email} - {full_address} - "
        + (f"${monthly_quote}/month" if monthly_quote else "QT RQRD")
        + f" ({actual_size} acres, tier: {tier_label})"
    )

    return QuoteResponse(
        customer_id=customer.id,
        claimed_size=quote_request.claimed_size,
        actual_size=actual_size,
        monthly_quote=monthly_quote,
        size_verified=size_verified,
        quote_required=quote_required,
        tier_label=tier_label,
    )


@router.get("/pricing")
async def get_pricing():
    """Get current pricing tiers."""
    return load_rates_raw()


@router.post("/schedule-service/{customer_id}", response_model=ServiceScheduleResponse)
async def schedule_service(
    customer_id: int,
    service_request: ServiceStartRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ServiceScheduleResponse:
    """
    Schedule service start date for a purchased quote.

    The quote must be purchased before scheduling service.
    Start date must be at least service_lead_days in the future.
    """
    # Fetch the customer record
    result = await db.execute(
        select(Customer).where(Customer.id == customer_id)
    )
    customer = result.scalar_one_or_none()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quote not found",
        )

    # Verify ownership
    if customer.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to schedule this service",
        )

    # Must be purchased first
    if not customer.purchased:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quote must be purchased before scheduling service",
        )

    # Validate start date is in the future with lead time
    min_start_date = date.today() + timedelta(days=settings.service_lead_days)
    if service_request.service_start_date < min_start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Service start date must be at least {settings.service_lead_days} days from today",
        )

    # Update customer record
    customer.service_start_date = service_request.service_start_date
    customer.service_frequency = service_request.service_frequency.value
    customer.service_status = "active"

    await db.commit()
    await db.refresh(customer)

    logger.info(
        f"Service scheduled: customer {customer_id}, "
        f"start {service_request.service_start_date}, "
        f"frequency {service_request.service_frequency.value}"
    )

    return ServiceScheduleResponse(
        customer_id=customer.id,
        service_start_date=customer.service_start_date,
        service_frequency=customer.service_frequency,
        service_status=customer.service_status,
        fieldroutes_synced=customer.fieldroutes_customer_id is not None,
    )


@router.get("/my-service/{customer_id}", response_model=CustomerWithServiceResponse)
async def get_my_service(
    customer_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Customer:
    """
    Get service details for a customer quote.
    """
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.user_id == current_user.id,
        )
    )
    customer = result.scalar_one_or_none()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quote not found",
        )

    return customer
