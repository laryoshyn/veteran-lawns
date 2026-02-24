"""Stripe payment endpoints."""

import logging
from datetime import date, timedelta
from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from config import get_settings
from database import get_db
from models import Customer, User
from schemas import CheckoutResponse, WebhookResponse
from services.fieldroutes import sync_customer_to_fieldroutes

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()

# Configure Stripe
stripe.api_key = settings.stripe_secret_key


@router.post("/create-checkout/{customer_id}", response_model=CheckoutResponse)
async def create_checkout_session(
    customer_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CheckoutResponse:
    """
    Create a Stripe Checkout session for a quote.

    The customer must own the quote to create a checkout session.
    Returns a URL to redirect the user to Stripe's hosted checkout page.
    """
    # Fetch the customer/quote record
    result = await db.execute(
        select(Customer).where(Customer.id == customer_id)
    )
    customer = result.scalar_one_or_none()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quote not found",
        )

    # Verify ownership (customer must own this quote)
    if customer.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to purchase this quote",
        )

    # Check if already purchased
    if customer.purchased:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This quote has already been purchased",
        )

    # Validate quote amount
    if not customer.quote or customer.quote <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid quote amount",
        )

    try:
        # Create Stripe Checkout Session for subscription
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
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
                }
            ],
            mode="subscription",
            success_url=f"{_get_base_url()}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{_get_base_url()}/payment/cancel",
            customer_email=current_user.email,
            metadata={
                "customer_id": str(customer_id),
                "user_id": str(current_user.id),
                "quote_amount": str(customer.quote),
            },
        )

        logger.info(
            f"Checkout session created: {checkout_session.id} "
            f"for customer {customer_id} by user {current_user.email}"
        )

        return CheckoutResponse(checkout_url=checkout_session.url)

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating checkout: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment service error. Please try again later.",
        )


@router.post("/webhook", response_model=WebhookResponse)
async def stripe_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    stripe_signature: Annotated[str | None, Header(alias="stripe-signature")] = None,
) -> WebhookResponse:
    """
    Handle Stripe webhook events.

    Verifies the webhook signature and processes payment events.
    This endpoint should be configured in Stripe Dashboard.
    """
    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing stripe-signature header",
        )

    # Get raw request body for signature verification
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload,
            stripe_signature,
            settings.stripe_webhook_secret,
        )
    except ValueError as e:
        logger.error(f"Invalid webhook payload: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payload",
        )
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid webhook signature: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature",
        )

    # Handle the event
    if event["type"] == "checkout.session.completed":
        await _handle_checkout_completed(event["data"]["object"], db)
    elif event["type"] == "customer.subscription.deleted":
        await _handle_subscription_cancelled(event["data"]["object"], db)
    else:
        logger.info(f"Unhandled webhook event type: {event['type']}")

    return WebhookResponse(status="success")


async def _handle_checkout_completed(session: dict, db: AsyncSession) -> None:
    """Process successful checkout completion and sync to FieldRoutes."""
    customer_id = session.get("metadata", {}).get("customer_id")

    if not customer_id:
        logger.error(f"Checkout completed without customer_id: {session['id']}")
        return

    result = await db.execute(
        select(Customer).where(Customer.id == int(customer_id))
    )
    customer = result.scalar_one_or_none()

    if not customer:
        logger.error(f"Customer not found for checkout: {customer_id}")
        return

    # Update customer record
    customer.purchased = True
    customer.stripe_payment_id = session["id"]

    # Set default service start date if not already set
    if not customer.service_start_date:
        customer.service_start_date = date.today() + timedelta(days=settings.service_lead_days)
        customer.service_frequency = "weekly"
        customer.service_status = "pending"

    await db.commit()
    await db.refresh(customer)

    logger.info(
        f"Payment completed: customer {customer_id}, "
        f"session {session['id']}, amount ${customer.quote}"
    )

    # Sync to FieldRoutes (async, non-blocking)
    await _sync_to_fieldroutes(customer)


async def _sync_to_fieldroutes(customer: Customer) -> None:
    """Sync customer to FieldRoutes after payment."""
    if customer.fieldroutes_customer_id:
        logger.info(f"Customer {customer.id} already synced to FieldRoutes")
        return

    try:
        start_date_str = customer.service_start_date.isoformat() if customer.service_start_date else None
        if not start_date_str:
            logger.warning(f"Customer {customer.id} has no service start date, skipping FieldRoutes sync")
            return

        fr_customer_id, fr_subscription_id = await sync_customer_to_fieldroutes(
            name=customer.name,
            email=customer.email,
            address=customer.address,
            phone=customer.phone,
            frequency=customer.service_frequency or "weekly",
            start_date=start_date_str,
            monthly_rate=customer.quote or 0,
        )

        if fr_customer_id:
            # Note: We can't update the customer here since db session may be closed
            # This would need to be handled differently in production
            logger.info(
                f"FieldRoutes sync initiated for customer {customer.id}: "
                f"FR customer={fr_customer_id}, subscription={fr_subscription_id}"
            )
        else:
            logger.warning(f"FieldRoutes sync failed for customer {customer.id}")

    except Exception as e:
        # Don't fail the webhook if FieldRoutes sync fails
        logger.exception(f"FieldRoutes sync error for customer {customer.id}: {e}")


async def _handle_subscription_cancelled(subscription: dict, db: AsyncSession) -> None:
    """Process subscription cancellation."""
    # Find customer by stripe payment ID
    session_id = subscription.get("metadata", {}).get("checkout_session_id")

    if session_id:
        result = await db.execute(
            select(Customer).where(Customer.stripe_payment_id == session_id)
        )
        customer = result.scalar_one_or_none()

        if customer:
            customer.purchased = False
            await db.commit()
            logger.info(f"Subscription cancelled for customer {customer.id}")


def _get_base_url() -> str:
    """Get the base URL for redirects."""
    # In production, this should come from settings
    if settings.debug:
        return "http://localhost:8000"
    return "https://veteranlawnsandlandscapes.com"
