"""PM (Project Manager) tools and dashboard endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, require_role
from config import get_settings
from database import get_db
from models import LandscapingProject, User
from schemas import (
    LandscapingProjectResponse,
    ROMCalculateRequest,
    ROMEstimateResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()

# PM role requirement
require_pm = require_role("pm")


@router.get("/projects", response_model=list[LandscapingProjectResponse])
async def get_pm_projects(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_pm)],
    status_filter: str | None = None,
) -> list[LandscapingProject]:
    """
    Get all projects assigned to or available for the current PM.

    Optionally filter by project status.
    """
    query = select(LandscapingProject)

    # Filter by status if provided
    if status_filter:
        query = query.where(LandscapingProject.project_status == status_filter)

    # Show projects assigned to this PM or unassigned
    query = query.where(
        (LandscapingProject.assigned_pm_id == current_user.id) |
        (LandscapingProject.assigned_pm_id.is_(None))
    )

    query = query.order_by(LandscapingProject.created_at.desc())

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/my-assigned", response_model=list[LandscapingProjectResponse])
async def get_my_assigned_projects(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_pm)],
) -> list[LandscapingProject]:
    """
    Get only projects assigned to the current PM.
    """
    result = await db.execute(
        select(LandscapingProject)
        .where(LandscapingProject.assigned_pm_id == current_user.id)
        .order_by(LandscapingProject.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/claim/{project_id}")
async def claim_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_pm)],
):
    """
    Claim an unassigned project.

    PM role required. Project must not already be assigned.
    """
    result = await db.execute(
        select(LandscapingProject).where(LandscapingProject.id == project_id)
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    if project.assigned_pm_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project already assigned to a PM",
        )

    project.assigned_pm_id = current_user.id
    await db.commit()

    logger.info(f"Project {project_id} claimed by PM {current_user.email}")

    return {"status": "success", "message": "Project claimed successfully"}


@router.post("/calculate-rom", response_model=ROMEstimateResponse)
async def calculate_rom(
    rom_request: ROMCalculateRequest,
    current_user: Annotated[User, Depends(require_pm)],
) -> ROMEstimateResponse:
    """
    Calculate ROM (Rough Order of Magnitude) estimate.

    Uses configured labor rates and applies contingency percentage.
    Returns a low-high range for T&M proposal.
    """
    # Calculate labor costs
    labor_cost_base = rom_request.labor_hours * settings.labor_rate_standard
    labor_cost_with_pm = labor_cost_base * 1.2  # 20% premium for PM oversight

    # Apply contingency
    contingency_factor = 1 + (rom_request.contingency_percent / 100)

    # Calculate totals
    materials_with_contingency = rom_request.materials_cost * contingency_factor

    total_low = labor_cost_base + rom_request.materials_cost
    total_high = (labor_cost_with_pm * contingency_factor) + materials_with_contingency

    return ROMEstimateResponse(
        labor_hours=rom_request.labor_hours,
        materials_cost=rom_request.materials_cost,
        labor_cost_low=round(labor_cost_base, 2),
        labor_cost_high=round(labor_cost_with_pm * contingency_factor, 2),
        total_estimate_low=round(total_low, 2),
        total_estimate_high=round(total_high, 2),
    )


@router.post("/complete-visit/{project_id}")
async def complete_pm_visit(
    project_id: int,
    visit_notes: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_pm)],
):
    """
    Mark PM visit as completed and add notes.

    PM role required. Used after the on-site visit.
    """
    result = await db.execute(
        select(LandscapingProject).where(LandscapingProject.id == project_id)
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    if not project.pm_visit_requested:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No PM visit scheduled for this project",
        )

    if project.pm_visit_completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PM visit already marked as completed",
        )

    project.pm_visit_completed = True
    project.pm_visit_notes = visit_notes.get("notes", "")
    project.project_status = "prd_pending"

    if not project.assigned_pm_id:
        project.assigned_pm_id = current_user.id

    await db.commit()

    logger.info(f"PM visit completed for project {project_id} by {current_user.email}")

    return {"status": "success", "message": "PM visit marked as completed"}


@router.get("/stats")
async def get_pm_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_pm)],
):
    """
    Get statistics for PM dashboard.

    Shows counts of projects in various states.
    """
    # Total projects assigned to this PM
    total_assigned = await db.scalar(
        select(func.count(LandscapingProject.id))
        .where(LandscapingProject.assigned_pm_id == current_user.id)
    )

    # Projects pending PRD
    pending_prd = await db.scalar(
        select(func.count(LandscapingProject.id))
        .where(
            LandscapingProject.assigned_pm_id == current_user.id,
            LandscapingProject.project_status == "prd_pending",
        )
    )

    # Projects with proposals sent
    proposals_sent = await db.scalar(
        select(func.count(LandscapingProject.id))
        .where(
            LandscapingProject.assigned_pm_id == current_user.id,
            LandscapingProject.proposal_sent == True,  # noqa: E712
        )
    )

    # Accepted projects
    accepted = await db.scalar(
        select(func.count(LandscapingProject.id))
        .where(
            LandscapingProject.assigned_pm_id == current_user.id,
            LandscapingProject.customer_response == "accepted",
        )
    )

    # Total estimated revenue from accepted proposals
    total_revenue = await db.scalar(
        select(func.sum(LandscapingProject.rom_estimate_low))
        .where(
            LandscapingProject.assigned_pm_id == current_user.id,
            LandscapingProject.customer_response == "accepted",
        )
    )

    # Unassigned projects available to claim
    unassigned = await db.scalar(
        select(func.count(LandscapingProject.id))
        .where(LandscapingProject.assigned_pm_id.is_(None))
    )

    return {
        "total_assigned": total_assigned or 0,
        "pending_prd": pending_prd or 0,
        "proposals_sent": proposals_sent or 0,
        "accepted": accepted or 0,
        "total_revenue": round(total_revenue or 0, 2),
        "unassigned_available": unassigned or 0,
    }


@router.post("/start-project/{project_id}")
async def start_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_pm)],
):
    """
    Mark project as in progress.

    PM role required. Project must be in 'accepted' status.
    """
    result = await db.execute(
        select(LandscapingProject).where(LandscapingProject.id == project_id)
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    if project.project_status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project must be accepted before starting",
        )

    project.project_status = "in_progress"
    await db.commit()

    logger.info(f"Project {project_id} started by PM {current_user.email}")

    return {"status": "success", "project_status": "in_progress"}


@router.post("/complete-project/{project_id}")
async def complete_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_pm)],
):
    """
    Mark project as completed.

    PM role required. Project must be in 'in_progress' status.
    """
    result = await db.execute(
        select(LandscapingProject).where(LandscapingProject.id == project_id)
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    if project.project_status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project must be in progress before completing",
        )

    project.project_status = "completed"
    await db.commit()

    logger.info(f"Project {project_id} completed by PM {current_user.email}")

    return {"status": "success", "project_status": "completed"}
