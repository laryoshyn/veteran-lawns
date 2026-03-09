"""Job application endpoints."""

import logging
from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_admin
from database import get_db
from models import Employee, JobApplication, User
from services.email import send_hire_congratulation_email

logger = logging.getLogger(__name__)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

VALID_POSITIONS = {"lawn_service", "sales", "support"}
VALID_WORK_AUTH = {"citizen", "national", "permanent_resident", "work_visa"}


class JobApplicationRequest(BaseModel):
    name: str
    email: EmailStr
    phone: str
    position: str
    authorized_to_work: bool
    requires_sponsorship: bool
    work_auth_status: str
    availability_date: str | None = None
    message: str | None = None


class JobApplicationResponse(BaseModel):
    id: int
    message: str


@router.post("/apply", response_model=JobApplicationResponse)
@limiter.limit("5/minute")
async def apply_for_job(
    request: Request,
    application: JobApplicationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobApplicationResponse:
    """Submit a job application."""
    if application.position not in VALID_POSITIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid position selected")

    if application.work_auth_status not in VALID_WORK_AUTH:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid work authorization status")

    availability = None
    if application.availability_date:
        try:
            availability = date_type.fromisoformat(application.availability_date)
        except ValueError:
            pass

    job_app = JobApplication(
        name=application.name,
        email=application.email,
        phone=application.phone,
        position=application.position,
        authorized_to_work=application.authorized_to_work,
        requires_sponsorship=application.requires_sponsorship,
        work_auth_status=application.work_auth_status,
        availability_date=availability,
        message=application.message,
    )
    db.add(job_app)
    await db.commit()
    await db.refresh(job_app)

    logger.info(
        f"Job application received: {job_app.id} - {application.email} - {application.position}"
    )

    return JobApplicationResponse(
        id=job_app.id,
        message="Application received! We'll be in touch within 3–5 business days.",
    )


VALID_STATUSES = {"new", "reviewing", "contacted", "hired", "rejected"}


@router.get("/applications")
async def get_applications(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    position: str | None = None,
    app_status: str | None = None,
    limit: int = 100,
):
    """Get all job applications (admin only)."""
    query = select(JobApplication).order_by(JobApplication.created_at.desc()).limit(limit)
    if position:
        query = query.where(JobApplication.position == position)
    if app_status:
        query = query.where(JobApplication.status == app_status)
    result = await db.execute(query)
    apps = result.scalars().all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "email": a.email,
            "phone": a.phone,
            "position": a.position,
            "authorized_to_work": a.authorized_to_work,
            "requires_sponsorship": a.requires_sponsorship,
            "work_auth_status": a.work_auth_status,
            "availability_date": a.availability_date.isoformat() if a.availability_date else None,
            "message": a.message,
            "status": a.status,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in apps
    ]


@router.patch("/applications/{application_id}")
async def update_application_status(
    application_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
    app_status: str,
):
    """Update a job application status (admin only)."""
    if app_status not in VALID_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")

    result = await db.execute(select(JobApplication).where(JobApplication.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    app.status = app_status
    await db.commit()
    logger.info(f"Admin {current_user.email} updated application {application_id} to '{app_status}'")
    return {"id": app.id, "status": app.status, "message": "Status updated"}


_POSITION_LABELS = {
    "lawn_service": "Lawn Service Team",
    "sales": "Sales",
    "support": "Support Team",
}


@router.post("/applications/{application_id}/hire")
async def hire_applicant(
    application_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
):
    """Accept applicant as employee, mark hired, send congratulation email."""
    result = await db.execute(select(JobApplication).where(JobApplication.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    if app.status == "hired":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Applicant already hired")

    emp = Employee(
        name=app.name,
        email=app.email,
        phone=app.phone,
        position=app.position,
        employment_type="full_time",
        hire_date=date_type.today(),
        authorized_to_work=app.authorized_to_work,
        requires_sponsorship=app.requires_sponsorship,
        work_auth_status=app.work_auth_status,
    )
    db.add(emp)
    app.status = "hired"
    await db.commit()
    await db.refresh(emp)

    email_sent = await send_hire_congratulation_email(
        to_email=app.email,
        applicant_name=app.name,
        position_label=_POSITION_LABELS.get(app.position, app.position),
    )
    logger.info(f"Admin {current_user.email} hired applicant {application_id} → employee {emp.id}, email_sent={email_sent}")
    return {"employee_id": emp.id, "email_sent": email_sent}
