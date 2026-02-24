"""Tests for quote endpoints."""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models import Customer, User
from tests.conftest import get_auth_headers


@pytest.mark.asyncio
async def test_get_pricing(client: AsyncClient):
    """Test pricing endpoint returns tiered rate structure."""
    response = await client.get("/quotes/pricing")
    assert response.status_code == 200
    data = response.json()
    assert "tiers" in data
    assert len(data["tiers"]) >= 1
    # Last tier should require a quote
    last_tier = data["tiers"][-1]
    assert last_tier["quote_required"] is True
    assert last_tier["price"] is None


@pytest.mark.asyncio
async def test_create_quote(client: AsyncClient):
    """Test creating a new quote estimate."""
    quote_data = {
        "name": "John Doe",
        "email": "john@example.com",
        "street_address": "123 Main St",
        "city": "Bel Air",
        "zipcode": "21014",
        "phone": "410-555-1234",
        "claimed_size": 0.5,
    }
    response = await client.post("/quotes/estimate", json=quote_data)
    assert response.status_code == 200
    data = response.json()
    assert "customer_id" in data
    assert "monthly_quote" in data
    assert data["claimed_size"] == 0.5


@pytest.mark.asyncio
async def test_create_quote_invalid_email(client: AsyncClient):
    """Test quote creation with invalid email fails."""
    quote_data = {
        "name": "John Doe",
        "email": "invalid-email",
        "street_address": "123 Main St",
        "city": "Bel Air",
        "zipcode": "21014",
        "phone": "410-555-1234",
        "claimed_size": 0.5,
    }
    response = await client.post("/quotes/estimate", json=quote_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_quote_invalid_zipcode(client: AsyncClient):
    """Test quote creation with invalid zipcode fails."""
    quote_data = {
        "name": "John Doe",
        "email": "john@example.com",
        "street_address": "123 Main St",
        "city": "Bel Air",
        "zipcode": "invalid",
        "phone": "410-555-1234",
        "claimed_size": 0.5,
    }
    response = await client.post("/quotes/estimate", json=quote_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_schedule_service_requires_auth(client: AsyncClient, test_customer: Customer):
    """Test schedule service requires authentication."""
    schedule_data = {
        "service_start_date": (date.today() + timedelta(days=7)).isoformat(),
        "service_frequency": "weekly",
    }
    response = await client.post(
        f"/quotes/schedule-service/{test_customer.id}",
        json=schedule_data,
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_schedule_service_requires_purchase(
    client: AsyncClient,
    test_customer: Customer,
    test_user: User,
):
    """Test scheduling service requires the quote to be purchased first."""
    headers = get_auth_headers(test_user.id)
    schedule_data = {
        "service_start_date": (date.today() + timedelta(days=7)).isoformat(),
        "service_frequency": "weekly",
    }
    response = await client.post(
        f"/quotes/schedule-service/{test_customer.id}",
        json=schedule_data,
        headers=headers,
    )
    assert response.status_code == 400
    assert "purchased" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_schedule_service_success(
    client: AsyncClient,
    purchased_customer: Customer,
    test_user: User,
):
    """Test successful service scheduling."""
    headers = get_auth_headers(test_user.id)
    start_date = date.today() + timedelta(days=7)
    schedule_data = {
        "service_start_date": start_date.isoformat(),
        "service_frequency": "weekly",
    }
    response = await client.post(
        f"/quotes/schedule-service/{purchased_customer.id}",
        json=schedule_data,
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["service_start_date"] == start_date.isoformat()
    assert data["service_frequency"] == "weekly"
    assert data["service_status"] == "active"


@pytest.mark.asyncio
async def test_schedule_service_date_too_soon(
    client: AsyncClient,
    purchased_customer: Customer,
    test_user: User,
):
    """Test scheduling service with date too soon fails."""
    headers = get_auth_headers(test_user.id)
    # Try to schedule for tomorrow (less than 3 day lead time)
    schedule_data = {
        "service_start_date": (date.today() + timedelta(days=1)).isoformat(),
        "service_frequency": "weekly",
    }
    response = await client.post(
        f"/quotes/schedule-service/{purchased_customer.id}",
        json=schedule_data,
        headers=headers,
    )
    assert response.status_code == 400
    assert "days" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_schedule_service_not_found(
    client: AsyncClient,
    test_user: User,
):
    """Test scheduling service for non-existent quote."""
    headers = get_auth_headers(test_user.id)
    schedule_data = {
        "service_start_date": (date.today() + timedelta(days=7)).isoformat(),
        "service_frequency": "weekly",
    }
    response = await client.post(
        "/quotes/schedule-service/99999",
        json=schedule_data,
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_my_service(
    client: AsyncClient,
    purchased_customer: Customer,
    test_user: User,
):
    """Test getting service details."""
    headers = get_auth_headers(test_user.id)
    response = await client.get(
        f"/quotes/my-service/{purchased_customer.id}",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == purchased_customer.id
    assert data["purchased"] is True
