"""FieldRoutes API client for customer and subscription management."""

import logging
from dataclasses import dataclass

import httpx

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

REQUEST_TIMEOUT = 30.0


@dataclass
class FieldRoutesCustomer:
    """FieldRoutes customer data."""

    customer_id: str
    name: str
    email: str
    address: str
    phone: str


@dataclass
class FieldRoutesSubscription:
    """FieldRoutes subscription data."""

    subscription_id: str
    customer_id: str
    service_type: str
    frequency: str
    start_date: str


class FieldRoutesError(Exception):
    """FieldRoutes API error."""

    pass


async def create_fieldroutes_customer(
    name: str,
    email: str,
    address: str,
    phone: str,
) -> FieldRoutesCustomer | None:
    """
    Create a customer in FieldRoutes.

    Args:
        name: Customer full name
        email: Customer email
        address: Service address
        phone: Customer phone

    Returns:
        FieldRoutesCustomer if successful, None if API unavailable
    """
    if not settings.fieldroutes_api_key or not settings.fieldroutes_account_id:
        logger.warning("FieldRoutes API not configured, skipping customer creation")
        return None

    url = f"{settings.fieldroutes_api_url}/customers"
    headers = {
        "Authorization": f"Bearer {settings.fieldroutes_api_key}",
        "X-Account-ID": settings.fieldroutes_account_id,
        "Content-Type": "application/json",
    }
    payload = {
        "name": name,
        "email": email,
        "serviceAddress": address,
        "phone": phone,
        "customerType": "residential",
        "source": "veteran_lawns_website",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

            customer = FieldRoutesCustomer(
                customer_id=data["id"],
                name=data["name"],
                email=data["email"],
                address=data["serviceAddress"],
                phone=data["phone"],
            )
            logger.info(f"Created FieldRoutes customer: {customer.customer_id}")
            return customer

    except httpx.TimeoutException:
        logger.error("FieldRoutes API timeout during customer creation")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"FieldRoutes API error: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        logger.exception(f"FieldRoutes API error: {e}")
        return None


async def create_fieldroutes_subscription(
    customer_id: str,
    service_type: str,
    frequency: str,
    start_date: str,
    monthly_rate: float,
) -> FieldRoutesSubscription | None:
    """
    Create a recurring service subscription in FieldRoutes.

    Args:
        customer_id: FieldRoutes customer ID
        service_type: Type of service (e.g., "lawn_mowing")
        frequency: Service frequency (weekly, biweekly, monthly)
        start_date: Service start date (YYYY-MM-DD)
        monthly_rate: Monthly service rate in dollars

    Returns:
        FieldRoutesSubscription if successful, None if API unavailable
    """
    if not settings.fieldroutes_api_key or not settings.fieldroutes_account_id:
        logger.warning("FieldRoutes API not configured, skipping subscription creation")
        return None

    url = f"{settings.fieldroutes_api_url}/subscriptions"
    headers = {
        "Authorization": f"Bearer {settings.fieldroutes_api_key}",
        "X-Account-ID": settings.fieldroutes_account_id,
        "Content-Type": "application/json",
    }

    # Map frequency to FieldRoutes format
    frequency_map = {
        "weekly": "WEEKLY",
        "biweekly": "BIWEEKLY",
        "monthly": "MONTHLY",
    }
    fr_frequency = frequency_map.get(frequency, "WEEKLY")

    payload = {
        "customerId": customer_id,
        "serviceType": service_type,
        "frequency": fr_frequency,
        "startDate": start_date,
        "monthlyRate": monthly_rate,
        "autoRenew": True,
        "status": "active",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

            subscription = FieldRoutesSubscription(
                subscription_id=data["id"],
                customer_id=customer_id,
                service_type=data["serviceType"],
                frequency=data["frequency"],
                start_date=data["startDate"],
            )
            logger.info(f"Created FieldRoutes subscription: {subscription.subscription_id}")
            return subscription

    except httpx.TimeoutException:
        logger.error("FieldRoutes API timeout during subscription creation")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"FieldRoutes API error: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        logger.exception(f"FieldRoutes API error: {e}")
        return None


async def sync_customer_to_fieldroutes(
    name: str,
    email: str,
    address: str,
    phone: str,
    frequency: str,
    start_date: str,
    monthly_rate: float,
) -> tuple[str | None, str | None]:
    """
    Full sync: create customer and subscription in FieldRoutes.

    Args:
        name: Customer name
        email: Customer email
        address: Service address
        phone: Customer phone
        frequency: Service frequency
        start_date: Start date (YYYY-MM-DD)
        monthly_rate: Monthly rate

    Returns:
        Tuple of (customer_id, subscription_id) or (None, None) if failed
    """
    # Create customer first
    customer = await create_fieldroutes_customer(name, email, address, phone)
    if not customer:
        return None, None

    # Then create subscription
    subscription = await create_fieldroutes_subscription(
        customer_id=customer.customer_id,
        service_type="lawn_mowing",
        frequency=frequency,
        start_date=start_date,
        monthly_rate=monthly_rate,
    )

    if not subscription:
        logger.warning(
            f"Customer {customer.customer_id} created but subscription failed"
        )
        return customer.customer_id, None

    return customer.customer_id, subscription.subscription_id


async def get_fieldroutes_customer(customer_id: str) -> FieldRoutesCustomer | None:
    """
    Get customer details from FieldRoutes.

    Args:
        customer_id: FieldRoutes customer ID

    Returns:
        FieldRoutesCustomer if found, None otherwise
    """
    if not settings.fieldroutes_api_key:
        return None

    url = f"{settings.fieldroutes_api_url}/customers/{customer_id}"
    headers = {
        "Authorization": f"Bearer {settings.fieldroutes_api_key}",
        "X-Account-ID": settings.fieldroutes_account_id,
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            return FieldRoutesCustomer(
                customer_id=data["id"],
                name=data["name"],
                email=data["email"],
                address=data["serviceAddress"],
                phone=data["phone"],
            )

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        logger.error(f"FieldRoutes API error: {e.response.status_code}")
        return None
    except Exception as e:
        logger.exception(f"FieldRoutes API error: {e}")
        return None


async def cancel_fieldroutes_subscription(subscription_id: str) -> bool:
    """
    Cancel a subscription in FieldRoutes.

    Args:
        subscription_id: FieldRoutes subscription ID

    Returns:
        True if cancelled successfully, False otherwise
    """
    if not settings.fieldroutes_api_key:
        return False

    url = f"{settings.fieldroutes_api_url}/subscriptions/{subscription_id}/cancel"
    headers = {
        "Authorization": f"Bearer {settings.fieldroutes_api_key}",
        "X-Account-ID": settings.fieldroutes_account_id,
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()
            logger.info(f"Cancelled FieldRoutes subscription: {subscription_id}")
            return True

    except Exception as e:
        logger.exception(f"Failed to cancel FieldRoutes subscription: {e}")
        return False
