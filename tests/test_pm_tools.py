"""Tests for PM tools endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models import LandscapingProject, User
from tests.conftest import get_auth_headers


@pytest.mark.asyncio
async def test_get_pm_projects_requires_pm(
    client: AsyncClient,
    test_user: User,
):
    """Test PM projects endpoint requires PM role."""
    headers = get_auth_headers(test_user.id)
    response = await client.get("/pm/projects", headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_pm_projects_success(
    client: AsyncClient,
    test_pm: User,
    test_landscaping_project: LandscapingProject,
):
    """Test PM can get projects."""
    headers = get_auth_headers(test_pm.id)
    response = await client.get("/pm/projects", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_claim_project(
    client: AsyncClient,
    test_pm: User,
    test_landscaping_project: LandscapingProject,
):
    """Test PM can claim an unassigned project."""
    headers = get_auth_headers(test_pm.id)
    response = await client.post(
        f"/pm/claim/{test_landscaping_project.id}",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


@pytest.mark.asyncio
async def test_claim_project_not_found(
    client: AsyncClient,
    test_pm: User,
):
    """Test claiming non-existent project fails."""
    headers = get_auth_headers(test_pm.id)
    response = await client.post("/pm/claim/99999", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_calculate_rom(
    client: AsyncClient,
    test_pm: User,
):
    """Test ROM calculation."""
    headers = get_auth_headers(test_pm.id)
    rom_data = {
        "labor_hours": 100,
        "materials_cost": 5000,
        "contingency_percent": 15,
    }
    response = await client.post("/pm/calculate-rom", json=rom_data, headers=headers)
    assert response.status_code == 200
    data = response.json()

    assert data["labor_hours"] == 100
    assert data["materials_cost"] == 5000
    assert "labor_cost_low" in data
    assert "labor_cost_high" in data
    assert "total_estimate_low" in data
    assert "total_estimate_high" in data

    # Check low estimate makes sense (labor + materials)
    assert data["total_estimate_low"] > 5000


@pytest.mark.asyncio
async def test_calculate_rom_requires_pm(
    client: AsyncClient,
    test_user: User,
):
    """Test ROM calculation requires PM role."""
    headers = get_auth_headers(test_user.id)
    rom_data = {
        "labor_hours": 100,
        "materials_cost": 5000,
    }
    response = await client.post("/pm/calculate-rom", json=rom_data, headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_pm_stats(
    client: AsyncClient,
    test_pm: User,
):
    """Test PM stats endpoint."""
    headers = get_auth_headers(test_pm.id)
    response = await client.get("/pm/stats", headers=headers)
    assert response.status_code == 200
    data = response.json()

    assert "total_assigned" in data
    assert "pending_prd" in data
    assert "proposals_sent" in data
    assert "accepted" in data
    assert "total_revenue" in data
    assert "unassigned_available" in data


@pytest.mark.asyncio
async def test_complete_visit_requires_scheduled(
    client: AsyncClient,
    test_pm: User,
    test_landscaping_project: LandscapingProject,
):
    """Test completing visit requires it to be scheduled first."""
    headers = get_auth_headers(test_pm.id)
    visit_notes = {"notes": "Good site, ready for work"}
    response = await client.post(
        f"/pm/complete-visit/{test_landscaping_project.id}",
        json=visit_notes,
        headers=headers,
    )
    assert response.status_code == 400
    assert "scheduled" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_start_project_requires_accepted(
    client: AsyncClient,
    test_pm: User,
    test_landscaping_project: LandscapingProject,
):
    """Test starting project requires accepted status."""
    headers = get_auth_headers(test_pm.id)
    response = await client.post(
        f"/pm/start-project/{test_landscaping_project.id}",
        headers=headers,
    )
    assert response.status_code == 400
    assert "accepted" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_complete_project_requires_in_progress(
    client: AsyncClient,
    test_pm: User,
    test_landscaping_project: LandscapingProject,
):
    """Test completing project requires in_progress status."""
    headers = get_auth_headers(test_pm.id)
    response = await client.post(
        f"/pm/complete-project/{test_landscaping_project.id}",
        headers=headers,
    )
    assert response.status_code == 400
    assert "in progress" in response.json()["detail"].lower()
