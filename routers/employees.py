"""Employee management endpoints."""

import logging
from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_admin
from database import get_db
from models import Employee, User

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_POSITIONS = {"lawn_service", "sales", "support", "manager"}
VALID_EMPLOYMENT_TYPES = {"full_time", "part_time", "contractor"}
VALID_STATUSES = {"active", "inactive", "terminated"}
VALID_WORK_AUTH = {"citizen", "national", "permanent_resident", "work_visa"}


def _serialize(e: Employee) -> dict:
    return {
        "id": e.id,
        "employee_id": e.employee_id,
        "name": e.name,
        "email": e.email,
        "phone": e.phone,
        "position": e.position,
        "employment_type": e.employment_type,
        "hire_date": e.hire_date.isoformat() if e.hire_date else None,
        "hourly_rate": e.hourly_rate,
        "status": e.status,
        "authorized_to_work": e.authorized_to_work,
        "requires_sponsorship": e.requires_sponsorship,
        "work_auth_status": e.work_auth_status,
        "ssn": e.ssn,
        "notes": e.notes,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


class EmployeeCreate(BaseModel):
    employee_id: str | None = None
    name: str
    email: EmailStr
    phone: str
    position: str
    employment_type: str = "full_time"
    hire_date: str | None = None
    hourly_rate: float | None = None
    authorized_to_work: bool | None = None
    requires_sponsorship: bool | None = None
    work_auth_status: str | None = None
    ssn: str | None = None
    notes: str | None = None


@router.get("/")
async def list_employees(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    emp_status: str | None = None,
    position: str | None = None,
):
    """List employees (admin only)."""
    query = select(Employee).order_by(Employee.name)
    if emp_status:
        query = query.where(Employee.status == emp_status)
    if position:
        query = query.where(Employee.position == position)
    result = await db.execute(query)
    return [_serialize(e) for e in result.scalars().all()]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_employee(
    body: EmployeeCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    """Add a new employee (admin only)."""
    if body.position not in VALID_POSITIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid position")
    if body.employment_type not in VALID_EMPLOYMENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid employment type")

    hire_date = None
    if body.hire_date:
        try:
            hire_date = date_type.fromisoformat(body.hire_date)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid hire date format. Use YYYY-MM-DD")

    if body.work_auth_status and body.work_auth_status not in VALID_WORK_AUTH:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid work authorization status")

    emp = Employee(
        employee_id=body.employee_id or None,
        name=body.name,
        email=body.email,
        phone=body.phone,
        position=body.position,
        employment_type=body.employment_type,
        hire_date=hire_date,
        hourly_rate=body.hourly_rate,
        authorized_to_work=body.authorized_to_work,
        requires_sponsorship=body.requires_sponsorship,
        work_auth_status=body.work_auth_status,
        ssn=body.ssn or None,
        notes=body.notes,
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    logger.info(f"Employee created: {emp.id} - {emp.name}")
    return _serialize(emp)


@router.patch("/{employee_id}")
async def update_employee(
    employee_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    emp_id: str | None = None,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    position: str | None = None,
    employment_type: str | None = None,
    hire_date: str | None = None,
    hourly_rate: float | None = None,
    emp_status: str | None = None,
    authorized_to_work: bool | None = None,
    requires_sponsorship: bool | None = None,
    work_auth_status: str | None = None,
    ssn: str | None = None,
    notes: str | None = None,
):
    """Update employee details (admin only)."""
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    if emp_id is not None:
        emp.employee_id = emp_id or None
    if name is not None:
        emp.name = name
    if email is not None:
        emp.email = email
    if phone is not None:
        emp.phone = phone
    if position is not None:
        if position not in VALID_POSITIONS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid position")
        emp.position = position
    if employment_type is not None:
        if employment_type not in VALID_EMPLOYMENT_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid employment type")
        emp.employment_type = employment_type
    if hire_date is not None:
        try:
            emp.hire_date = date_type.fromisoformat(hire_date)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid hire date format. Use YYYY-MM-DD")
    if hourly_rate is not None:
        emp.hourly_rate = hourly_rate
    if emp_status is not None:
        if emp_status not in VALID_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")
        emp.status = emp_status
    if authorized_to_work is not None:
        emp.authorized_to_work = authorized_to_work
    if requires_sponsorship is not None:
        emp.requires_sponsorship = requires_sponsorship
    if work_auth_status is not None:
        if work_auth_status not in VALID_WORK_AUTH:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid work authorization status")
        emp.work_auth_status = work_auth_status
    if ssn is not None:
        emp.ssn = ssn or None
    if notes is not None:
        emp.notes = notes

    await db.commit()
    logger.info(f"Employee updated: {employee_id}")
    return _serialize(emp)


@router.delete("/{employee_id}")
async def terminate_employee(
    employee_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    """Terminate an employee (sets status to terminated, admin only)."""
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    emp.status = "terminated"
    await db.commit()
    logger.info(f"Employee terminated: {employee_id}")
    return {"message": "Employee terminated"}
