"""Crew management endpoints — accessible to admin and manager roles."""

import asyncio
import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import require_manager
from database import get_db
from models import Crew, Customer, Employee, User, crew_members
from services.email import send_crew_schedule_email
from services.openai_size import route_crew_customers

logger = logging.getLogger(__name__)
router = APIRouter()

CREW_ID_PREFIX = "CRW-"

# Always eager-load relationships to avoid greenlet/lazy-load errors in async
_crew_q = select(Crew).options(selectinload(Crew.members), selectinload(Crew.customers))


async def _next_crew_id(db: AsyncSession) -> str:
    result = await db.execute(
        select(func.max(Crew.crew_id)).where(Crew.crew_id.like(f"{CREW_ID_PREFIX}%"))
    )
    last = result.scalar_one_or_none()
    if last:
        try:
            num = int(last[len(CREW_ID_PREFIX):]) + 1
        except ValueError:
            num = 1
    else:
        num = 1
    return f"{CREW_ID_PREFIX}{num:06d}"


def _serialize(crew: Crew) -> dict:
    return {
        "id": crew.id,
        "crew_id": crew.crew_id,
        "name": crew.name,
        "status": crew.status,
        "created_at": crew.created_at.isoformat() if crew.created_at else None,
        "members": [
            {
                "id": m.id,
                "employee_id": m.employee_id,
                "name": m.name,
                "position": m.position,
                "status": m.status,
            }
            for m in crew.members
        ],
        "customers": _ordered_customers(crew),
    }


def _ordered_customers(crew: Crew) -> list[dict]:
    order = []
    if crew.customer_order:
        try:
            order = json.loads(crew.customer_order)
        except (ValueError, TypeError):
            order = []
    order_map = {cid: i for i, cid in enumerate(order)}
    sorted_custs = sorted(crew.customers, key=lambda c: order_map.get(c.id, 9999))
    return [
        {
            "id": c.id,
            "name": c.name,
            "address": c.address,
            "phone": c.phone,
            "actual_size": c.actual_size,
            "claimed_size": c.claimed_size,
            "lot_size_acres": c.lot_size_acres,
            "service_start_date": c.service_start_date.isoformat() if c.service_start_date else None,
            "service_frequency": c.service_frequency,
            "service_status": c.service_status,
        }
        for c in sorted_custs
    ]


class CrewCreate(BaseModel):
    name: str


class CrewUpdate(BaseModel):
    name: str | None = None
    status: str | None = None


# ── CRUD ───────────────────────────────────────────────────────────────────────

@router.get("/")
async def list_crews(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
    crew_status: str | None = None,
):
    query = _crew_q.order_by(Crew.crew_id)
    if crew_status:
        query = query.where(Crew.status == crew_status)
    result = await db.execute(query)
    return [_serialize(c) for c in result.scalars().unique().all()]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_crew(
    body: CrewCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
):
    crew = Crew(
        crew_id=await _next_crew_id(db),
        name=body.name.strip(),
        status="active",
    )
    db.add(crew)
    await db.commit()
    result = await db.execute(_crew_q.where(Crew.id == crew.id))
    crew = result.scalar_one()
    logger.info(f"Crew created: {crew.crew_id} — {crew.name}")
    return _serialize(crew)


@router.patch("/{crew_id}")
async def update_crew(
    crew_id: int,
    body: CrewUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
):
    result = await db.execute(_crew_q.where(Crew.id == crew_id))
    crew = result.scalar_one_or_none()
    if not crew:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crew not found")
    if body.name is not None:
        crew.name = body.name.strip()
    if body.status is not None:
        if body.status not in ("active", "inactive"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")
        crew.status = body.status
    await db.commit()
    result2 = await db.execute(_crew_q.where(Crew.id == crew_id))
    return _serialize(result2.scalar_one())


@router.delete("/{crew_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_crew(
    crew_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
):
    """Permanently delete a crew, unassigning all its members and customers."""
    result = await db.execute(_crew_q.where(Crew.id == crew_id))
    crew = result.scalar_one_or_none()
    if not crew:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crew not found")
    # Unassign customers so they become available again
    for cust in crew.customers:
        cust.crew_id = None
    crew.members.clear()
    await db.flush()
    await db.delete(crew)
    await db.commit()
    logger.info(f"Crew deleted: {crew_id}")


# ── Members ────────────────────────────────────────────────────────────────────

@router.post("/{crew_id}/members/{employee_id}")
async def add_member(
    crew_id: int,
    employee_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
):
    crew_res = await db.execute(_crew_q.where(Crew.id == crew_id))
    crew = crew_res.scalar_one_or_none()
    if not crew:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crew not found")

    emp_res = await db.execute(select(Employee).where(Employee.id == employee_id))
    emp = emp_res.scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    if emp not in crew.members:
        crew.members.append(emp)
        await db.commit()
    result = await db.execute(_crew_q.where(Crew.id == crew_id))
    return _serialize(result.scalar_one())


@router.delete("/{crew_id}/members/{employee_id}")
async def remove_member(
    crew_id: int,
    employee_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
):
    crew_res = await db.execute(_crew_q.where(Crew.id == crew_id))
    crew = crew_res.scalar_one_or_none()
    if not crew:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crew not found")
    crew.members = [m for m in crew.members if m.id != employee_id]
    await db.commit()
    result = await db.execute(_crew_q.where(Crew.id == crew_id))
    return _serialize(result.scalar_one())


# ── Customer assignment ────────────────────────────────────────────────────────

@router.post("/{crew_id}/customers/{customer_id}")
async def assign_customer(
    crew_id: int,
    customer_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
):
    crew_res = await db.execute(_crew_q.where(Crew.id == crew_id))
    if not crew_res.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crew not found")

    cust_res = await db.execute(select(Customer).where(Customer.id == customer_id))
    cust = cust_res.scalar_one_or_none()
    if not cust:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    cust.crew_id = crew_id
    await db.commit()

    result = await db.execute(_crew_q.where(Crew.id == crew_id))
    return _serialize(result.scalar_one())


@router.delete("/{crew_id}/customers/{customer_id}")
async def unassign_customer(
    crew_id: int,
    customer_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
):
    cust_res = await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.crew_id == crew_id)
    )
    cust = cust_res.scalar_one_or_none()
    if not cust:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not in this crew")
    cust.crew_id = None
    await db.commit()
    return {"message": "Customer unassigned"}


class ReorderBody(BaseModel):
    order: list[int]  # ordered list of customer IDs


@router.post("/{crew_id}/reorder-customers")
async def reorder_customers(
    crew_id: int,
    body: ReorderBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
):
    result = await db.execute(_crew_q.where(Crew.id == crew_id))
    crew = result.scalar_one_or_none()
    if not crew:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crew not found")
    crew.customer_order = json.dumps(body.order)
    await db.commit()
    result2 = await db.execute(_crew_q.where(Crew.id == crew_id))
    return _serialize(result2.scalar_one())


@router.post("/{crew_id}/auto-route")
async def auto_route(
    crew_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
):
    """Use AI to reorder crew customers by optimal driving route."""
    result = await db.execute(_crew_q.where(Crew.id == crew_id))
    crew = result.scalar_one_or_none()
    if not crew:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crew not found")
    if not crew.customers:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No customers to route")

    # Preserve existing saved order before routing
    existing_order = []
    if crew.customer_order:
        try:
            existing_order = json.loads(crew.customer_order)
        except (ValueError, TypeError):
            existing_order = []
    order_map = {cid: i for i, cid in enumerate(existing_order)}
    sorted_custs = sorted(crew.customers, key=lambda c: order_map.get(c.id, 9999))

    addresses = [c.address for c in sorted_custs]
    optimal_indices = await route_crew_customers(addresses)

    ordered_ids = [sorted_custs[i].id for i in optimal_indices]
    crew.customer_order = json.dumps(ordered_ids)
    await db.commit()

    result2 = await db.execute(_crew_q.where(Crew.id == crew_id))
    return _serialize(result2.scalar_one())


# ── Geocoding ──────────────────────────────────────────────────────────────────

_nominatim_cache: dict[str, tuple[float, float] | None] = {}
_nominatim_last_call = 0.0


def _nominatim_query(q: str) -> tuple[float, float] | None:
    global _nominatim_last_call
    elapsed = time.monotonic() - _nominatim_last_call
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)
    _nominatim_last_call = time.monotonic()
    url = (
        "https://nominatim.openstreetmap.org/search?"
        + urllib.parse.urlencode({"q": q, "format": "json", "limit": "1", "countrycodes": "us"})
    )
    req = urllib.request.Request(url, headers={"User-Agent": "VeteranLawns/1.0 admin@veteranlawnsandlandscapes.com"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as exc:
        logger.warning("Nominatim error for %r: %s", q, exc)
    return None


def _nominatim_sync(address: str) -> tuple[float, float] | None:
    """Geocode exact address only — no fallback."""
    return _nominatim_query(address)


class GeocodeRequest(BaseModel):
    addresses: list[str]




@router.post("/geocode")
async def geocode_addresses(
    body: GeocodeRequest,
    _: Annotated[User, Depends(require_manager)],
):
    """Geocode a list of addresses via Nominatim (server-side). Returns [{lat, lon} | null]."""
    results = []
    for addr in body.addresses:
        if addr not in _nominatim_cache:
            _nominatim_cache[addr] = await asyncio.to_thread(_nominatim_sync, addr)
        coord = _nominatim_cache[addr]
        results.append({"lat": coord[0], "lon": coord[1]} if coord else None)
    return results


# ── Calendar data ──────────────────────────────────────────────────────────────

@router.get("/calendar")
async def get_calendar(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
):
    """Return all active/pending customers with service schedules for calendar display."""
    result = await db.execute(
        select(Customer).where(
            Customer.service_status.in_(["active", "pending"]),
            Customer.service_start_date.is_not(None),
        ).order_by(Customer.service_start_date)
    )
    return [
        {
            "id": c.id,
            "name": c.name,
            "address": c.address,
            "service_start_date": c.service_start_date.isoformat(),
            "service_frequency": c.service_frequency,
            "service_status": c.service_status,
            "crew_id": c.crew_id,
        }
        for c in result.scalars().all()
    ]


# ── Available employees & customers for assignment ─────────────────────────────

@router.get("/available-employees")
async def available_employees(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
):
    """Active employees not already assigned to any crew."""
    taken_subq = select(crew_members.c.employee_id)
    result = await db.execute(
        select(Employee)
        .where(Employee.status == "active")
        .where(~Employee.id.in_(taken_subq))
        .order_by(Employee.name)
    )
    return [
        {"id": e.id, "employee_id": e.employee_id, "name": e.name, "position": e.position}
        for e in result.scalars().all()
    ]


@router.get("/available-customers")
async def available_customers(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
):
    """Active/pending customers with a service schedule not yet assigned to any crew."""
    result = await db.execute(
        select(Customer).where(
            Customer.service_status.in_(["active", "pending"]),
            Customer.purchased == True,  # noqa: E712
            Customer.crew_id.is_(None),
        ).order_by(Customer.name)
    )
    return [
        {
            "id": c.id,
            "name": c.name,
            "address": c.address,
            "service_frequency": c.service_frequency,
            "service_start_date": c.service_start_date.isoformat() if c.service_start_date else None,
            "crew_id": c.crew_id,
        }
        for c in result.scalars().all()
    ]


# ── Send weekly schedule ────────────────────────────────────────────────────────

def _occurs_on(cust, d):
    """Return True if a customer's service occurs on date d."""
    start = cust.service_start_date
    if not start or not cust.service_frequency:
        return False
    if d < start:
        return False
    diff = (d - start).days
    if cust.service_frequency == "weekly":
        return diff % 7 == 0
    if cust.service_frequency == "biweekly":
        return diff % 14 == 0
    if cust.service_frequency == "monthly":
        return d.day == start.day
    return False


@router.post("/{crew_id}/send-schedule")
async def send_schedule(
    crew_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_manager)],
):
    """Email this week's service schedule (Mon–Sun) to every crew member."""
    result = await db.execute(_crew_q.where(Crew.id == crew_id))
    crew = result.scalar_one_or_none()
    if not crew:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crew not found")

    if not crew.members:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Crew has no members to email")

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    week_days = [week_start + timedelta(days=i) for i in range(7)]
    week_label = f"{week_start.strftime('%b %d')} \u2013 {week_end.strftime('%b %d, %Y')}"

    services = []
    for cust in crew.customers:
        dates_this_week = [d.strftime("%a %b %d") for d in week_days if _occurs_on(cust, d)]
        if not dates_this_week:
            continue
        services.append({
            "name": cust.name,
            "address": cust.address,
            "service_frequency": cust.service_frequency,
            "actual_size": cust.actual_size,
            "claimed_size": cust.claimed_size,
            "lot_size_acres": cust.lot_size_acres,
            "dates": dates_this_week,
        })

    if not services:
        return {"message": "No services scheduled this week \u2014 nothing sent."}

    sent, failed = 0, 0
    for member in crew.members:
        ok = await send_crew_schedule_email(
            to_email=member.email,
            member_name=member.name,
            crew_name=crew.name,
            week_label=week_label,
            services=services,
        )
        if ok:
            sent += 1
        else:
            failed += 1

    logger.info("Crew %s schedule emailed: %d sent, %d failed", crew.crew_id, sent, failed)

    if sent == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email not configured \u2014 no messages sent",
        )

    msg = f"Schedule sent to {sent} crew member{'s' if sent != 1 else ''} ({len(services)} stops this week)"
    if failed:
        msg += f"; {failed} failed"
    return {"message": msg}
