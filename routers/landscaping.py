"""Landscaping project endpoints."""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, require_role
from config import get_settings
from database import get_db
from models import LandscapingProject, User
from schemas import (
    BudgetRange,
    LandscapingInquiryRequest,
    LandscapingInquiryResponse,
    LandscapingOptionsResponse,
    LandscapingProjectResponse,
    PMVisitResponse,
    PMVisitScheduleRequest,
    ProjectScope,
    ProjectType,
    ProposalResponseRequest,
    ProposalSendRequest,
    TimelinePreference,
)
from services.maryland_api import fetch_actual_size

logger = logging.getLogger(__name__)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
settings = get_settings()

# PM role requirement
require_pm = require_role("pm")


def _enum_to_options(enum_class, labels: dict) -> list[dict]:
    """Convert enum to dropdown options with labels."""
    return [
        {"value": e.value, "label": labels.get(e.value, e.value)}
        for e in enum_class
    ]


@router.get("/options", response_model=LandscapingOptionsResponse)
async def get_landscaping_options() -> LandscapingOptionsResponse:
    """
    Get all available options for landscaping form dropdowns.

    Returns lists of project types, scopes, budget ranges, and timeline preferences.
    """
    project_type_labels = {
        "hardscape": "Hardscape (patios, walkways, retaining walls)",
        "softscape": "Softscape (planting, gardens, lawn installation)",
        "drainage": "Drainage Solutions",
        "irrigation": "Irrigation Systems",
        "custom": "Custom Project",
    }

    project_scope_labels = {
        "small": "Small (under 500 sq ft)",
        "medium": "Medium (500-2000 sq ft)",
        "large": "Large (over 2000 sq ft)",
        "custom": "Custom / Multiple Areas",
    }

    budget_range_labels = {
        "under_5k": "Under $5,000",
        "5k_to_15k": "$5,000 - $15,000",
        "15k_to_30k": "$15,000 - $30,000",
        "30k_to_50k": "$30,000 - $50,000",
        "over_50k": "Over $50,000",
    }

    timeline_labels = {
        "asap": "As soon as possible",
        "within_1_month": "Within 1 month",
        "within_3_months": "Within 3 months",
        "within_6_months": "Within 6 months",
        "flexible": "Flexible",
    }

    return LandscapingOptionsResponse(
        project_types=_enum_to_options(ProjectType, project_type_labels),
        project_scopes=_enum_to_options(ProjectScope, project_scope_labels),
        budget_ranges=_enum_to_options(BudgetRange, budget_range_labels),
        timeline_preferences=_enum_to_options(TimelinePreference, timeline_labels),
    )


@router.post("/inquiry", response_model=LandscapingInquiryResponse)
@limiter.limit("5/minute")
async def create_landscaping_inquiry(
    request: Request,
    inquiry: LandscapingInquiryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LandscapingInquiryResponse:
    """
    Submit a landscaping project inquiry.

    No registration required. Validates property with Maryland API.
    Rate limited to 5 requests per minute.
    """
    # Try to get lot size from Maryland API
    lot_size, parcel_id = await fetch_actual_size(
        inquiry.street_address,
        inquiry.city,
        inquiry.zipcode,
    )

    # Build full address
    full_address = f"{inquiry.street_address}, {inquiry.city}, MD {inquiry.zipcode}"

    # Create project record
    project = LandscapingProject(
        name=inquiry.name,
        email=inquiry.email,
        address=full_address,
        phone=inquiry.phone,
        parcel_id=parcel_id,
        lot_size_acres=lot_size,
        project_type=inquiry.project_type.value,
        project_scope=inquiry.project_scope.value,
        design_preference=inquiry.design_preference,
        budget_range=inquiry.budget_range.value if inquiry.budget_range else None,
        timeline_preference=inquiry.timeline_preference.value if inquiry.timeline_preference else None,
        project_description=inquiry.project_description,
        project_status="inquiry",
    )

    db.add(project)
    await db.commit()
    await db.refresh(project)

    logger.info(
        f"Landscaping inquiry created: {project.id} - {inquiry.email} - "
        f"{inquiry.project_type.value} - {inquiry.project_scope.value}"
    )

    return LandscapingInquiryResponse(
        id=project.id,
        name=project.name,
        address=project.address,
        project_type=project.project_type,
        project_scope=project.project_scope,
        project_status=project.project_status,
        created_at=project.created_at,
    )


@router.post("/schedule-pm-visit", response_model=PMVisitResponse)
async def schedule_pm_visit(
    visit_request: PMVisitScheduleRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PMVisitResponse:
    """
    Schedule a PM (Project Manager) site visit.

    The PM will visit the property to assess the project and create a PRD.
    """
    result = await db.execute(
        select(LandscapingProject).where(LandscapingProject.id == visit_request.project_id)
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    if project.pm_visit_completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PM visit already completed for this project",
        )

    # Validate date is in the future
    if visit_request.preferred_date <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Visit date must be in the future",
        )

    project.pm_visit_requested = True
    project.pm_visit_date = visit_request.preferred_date
    project.project_status = "pm_scheduled"

    if visit_request.notes:
        project.pm_visit_notes = visit_request.notes

    await db.commit()
    await db.refresh(project)

    logger.info(f"PM visit scheduled for project {project.id}: {visit_request.preferred_date}")

    return PMVisitResponse(
        project_id=project.id,
        pm_visit_date=project.pm_visit_date,
        pm_visit_requested=True,
        project_status=project.project_status,
    )


@router.get("/project/{project_id}", response_model=LandscapingProjectResponse)
async def get_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LandscapingProject:
    """
    Get landscaping project details.

    Customers can only view their own projects. Admins and PMs can view all.
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

    # Check authorization
    if current_user.role not in ("admin", "pm"):
        if project.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this project",
            )

    return project


@router.post("/upload-prd/{project_id}")
async def upload_prd(
    project_id: int,
    prd_data: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_pm)],
):
    """
    Upload PRD (Project Requirements Document) for a project.

    PM role required. This is done after the PM visit.
    """
    import json

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
            detail="PM visit must be scheduled before uploading PRD",
        )

    # Store PRD content as JSON
    project.prd_content = json.dumps(prd_data.get("prd_content", {}))
    project.prd_uploaded_at = datetime.now(timezone.utc)
    project.pm_visit_completed = True
    project.pm_visit_notes = prd_data.get("pm_visit_notes")
    project.project_status = "prd_pending"
    project.assigned_pm_id = current_user.id

    await db.commit()

    logger.info(f"PRD uploaded for project {project_id} by PM {current_user.email}")

    return {"status": "success", "message": "PRD uploaded successfully"}


@router.post("/send-proposal/{project_id}")
async def send_proposal(
    project_id: int,
    proposal: ProposalSendRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_pm)],
):
    """
    Send ROM T&M proposal to customer.

    PM role required. Project must have PRD uploaded first.
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

    if not project.prd_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PRD must be uploaded before sending proposal",
        )

    if project.proposal_sent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Proposal already sent for this project",
        )

    # Store ROM estimates
    project.rom_estimate_low = proposal.rom_estimate_low
    project.rom_estimate_high = proposal.rom_estimate_high
    project.rom_labor_hours = proposal.rom_labor_hours
    project.rom_materials_cost = proposal.rom_materials_cost
    project.proposal_sent = True
    project.proposal_sent_at = datetime.now(timezone.utc)
    project.customer_response = "pending"
    project.project_status = "proposal_sent"

    await db.commit()

    logger.info(
        f"Proposal sent for project {project_id}: "
        f"${proposal.rom_estimate_low:.2f} - ${proposal.rom_estimate_high:.2f}"
    )

    return {
        "status": "success",
        "message": "Proposal sent to customer",
        "estimate_range": f"${proposal.rom_estimate_low:.2f} - ${proposal.rom_estimate_high:.2f}",
    }


@router.post("/respond-proposal/{project_id}")
async def respond_to_proposal(
    project_id: int,
    response: ProposalResponseRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Customer responds to proposal (accept or decline).

    This endpoint can be used without authentication via email link.
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

    if not project.proposal_sent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No proposal has been sent for this project",
        )

    if project.customer_response in ("accepted", "declined"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Proposal already responded to",
        )

    project.customer_response = response.response.value
    project.customer_response_at = datetime.now(timezone.utc)

    if response.response.value == "accepted":
        project.project_status = "accepted"
    elif response.response.value == "declined":
        project.project_status = "cancelled"

    await db.commit()

    logger.info(f"Proposal response for project {project_id}: {response.response.value}")

    return {
        "status": "success",
        "response": response.response.value,
        "project_status": project.project_status,
    }


@router.get("/my-projects", response_model=list[LandscapingProjectResponse])
async def get_my_projects(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[LandscapingProject]:
    """
    Get all landscaping projects for the current user.
    """
    result = await db.execute(
        select(LandscapingProject)
        .where(LandscapingProject.user_id == current_user.id)
        .order_by(LandscapingProject.created_at.desc())
    )
    return list(result.scalars().all())
