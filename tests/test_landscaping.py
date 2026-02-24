"""Tests for landscaping endpoints."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models import LandscapingProject, User
from tests.conftest import get_auth_headers


@pytest.mark.asyncio
async def test_get_landscaping_options(client: AsyncClient):
    """Test getting dropdown options for landscaping form."""
    response = await client.get("/landscaping/options")
    assert response.status_code == 200
    data = response.json()

    assert "project_types" in data
    assert "project_scopes" in data
    assert "budget_ranges" in data
    assert "timeline_preferences" in data

    # Check project types
    types = [t["value"] for t in data["project_types"]]
    assert "hardscape" in types
    assert "softscape" in types
    assert "drainage" in types

    # Check scopes
    scopes = [s["value"] for s in data["project_scopes"]]
    assert "small" in scopes
    assert "medium" in scopes
    assert "large" in scopes


@pytest.mark.asyncio
async def test_create_landscaping_inquiry(client: AsyncClient):
    """Test creating a landscaping inquiry."""
    inquiry_data = {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "street_address": "456 Oak Lane",
        "city": "Bel Air",
        "zipcode": "21014",
        "phone": "410-555-9876",
        "project_type": "hardscape",
        "project_scope": "medium",
        "budget_range": "15k_to_30k",
        "timeline_preference": "within_3_months",
        "design_preference": "Modern",
        "project_description": "Want a new patio with built-in fire pit",
    }
    response = await client.post("/landscaping/inquiry", json=inquiry_data)
    assert response.status_code == 200
    data = response.json()

    assert data["name"] == "Jane Doe"
    assert data["project_type"] == "hardscape"
    assert data["project_scope"] == "medium"
    assert data["project_status"] == "inquiry"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_landscaping_inquiry_minimal(client: AsyncClient):
    """Test creating inquiry with only required fields."""
    inquiry_data = {
        "name": "Bob Smith",
        "email": "bob@example.com",
        "street_address": "789 Pine St",
        "city": "Fallston",
        "zipcode": "21047",
        "phone": "410-555-4321",
        "project_type": "softscape",
        "project_scope": "small",
    }
    response = await client.post("/landscaping/inquiry", json=inquiry_data)
    assert response.status_code == 200
    data = response.json()
    assert data["project_type"] == "softscape"


@pytest.mark.asyncio
async def test_create_landscaping_inquiry_invalid_type(client: AsyncClient):
    """Test inquiry with invalid project type fails."""
    inquiry_data = {
        "name": "Test User",
        "email": "test@example.com",
        "street_address": "123 Test St",
        "city": "Bel Air",
        "zipcode": "21014",
        "phone": "410-555-1234",
        "project_type": "invalid_type",
        "project_scope": "small",
    }
    response = await client.post("/landscaping/inquiry", json=inquiry_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_schedule_pm_visit(
    client: AsyncClient,
    test_landscaping_project: LandscapingProject,
):
    """Test scheduling a PM visit."""
    visit_date = datetime.now(timezone.utc) + timedelta(days=3)
    visit_data = {
        "project_id": test_landscaping_project.id,
        "preferred_date": visit_date.isoformat(),
        "notes": "Please call before arriving",
    }
    response = await client.post("/landscaping/schedule-pm-visit", json=visit_data)
    assert response.status_code == 200
    data = response.json()

    assert data["project_id"] == test_landscaping_project.id
    assert data["pm_visit_requested"] is True
    assert data["project_status"] == "pm_scheduled"


@pytest.mark.asyncio
async def test_schedule_pm_visit_past_date(
    client: AsyncClient,
    test_landscaping_project: LandscapingProject,
):
    """Test scheduling PM visit with past date fails."""
    past_date = datetime.now(timezone.utc) - timedelta(days=1)
    visit_data = {
        "project_id": test_landscaping_project.id,
        "preferred_date": past_date.isoformat(),
    }
    response = await client.post("/landscaping/schedule-pm-visit", json=visit_data)
    assert response.status_code == 400
    assert "future" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_schedule_pm_visit_not_found(client: AsyncClient):
    """Test scheduling PM visit for non-existent project."""
    visit_data = {
        "project_id": 99999,
        "preferred_date": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
    }
    response = await client.post("/landscaping/schedule-pm-visit", json=visit_data)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_project_requires_auth(
    client: AsyncClient,
    test_landscaping_project: LandscapingProject,
):
    """Test getting project details requires auth."""
    response = await client.get(f"/landscaping/project/{test_landscaping_project.id}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_respond_to_proposal_not_sent(
    client: AsyncClient,
    test_landscaping_project: LandscapingProject,
):
    """Test responding to proposal that hasn't been sent fails."""
    response_data = {"response": "accepted"}
    response = await client.post(
        f"/landscaping/respond-proposal/{test_landscaping_project.id}",
        json=response_data,
    )
    assert response.status_code == 400
    assert "proposal" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_prd_requires_pm(
    client: AsyncClient,
    test_landscaping_project: LandscapingProject,
    test_user: User,
):
    """Test uploading PRD requires PM role."""
    headers = get_auth_headers(test_user.id)  # Regular user, not PM
    prd_data = {"prd_content": {"requirements": []}}
    response = await client.post(
        f"/landscaping/upload-prd/{test_landscaping_project.id}",
        json=prd_data,
        headers=headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_send_proposal_requires_pm(
    client: AsyncClient,
    test_landscaping_project: LandscapingProject,
    test_user: User,
):
    """Test sending proposal requires PM role."""
    headers = get_auth_headers(test_user.id)
    proposal_data = {
        "rom_estimate_low": 15000,
        "rom_estimate_high": 20000,
        "rom_labor_hours": 100,
        "rom_materials_cost": 5000,
    }
    response = await client.post(
        f"/landscaping/send-proposal/{test_landscaping_project.id}",
        json=proposal_data,
        headers=headers,
    )
    assert response.status_code == 403
