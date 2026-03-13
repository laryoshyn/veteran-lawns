"""Seed 10 synthetic employees into the database."""

import asyncio
from datetime import date

from database import AsyncSessionLocal
from models import Employee


EMPLOYEES = [
    {
        "employee_id": "VLL-000001",
        "name": "Marcus Henderson",
        "email": "m.henderson@veteranlawns.com",
        "phone": "410-555-0101",
        "position": "lawn_service",
        "employment_type": "full_time",
        "hire_date": date(2022, 3, 14),
        "hourly_rate": 18.50,
        "authorized_to_work": True,
        "requires_sponsorship": False,
        "work_auth_status": "citizen",
        "status": "active",
    },
    {
        "employee_id": "VLL-000002",
        "name": "Delia Romero",
        "email": "d.romero@veteranlawns.com",
        "phone": "410-555-0102",
        "position": "lawn_service",
        "employment_type": "full_time",
        "hire_date": date(2023, 4, 3),
        "hourly_rate": 17.75,
        "authorized_to_work": True,
        "requires_sponsorship": False,
        "work_auth_status": "permanent_resident",
        "status": "active",
    },
    {
        "employee_id": "VLL-000003",
        "name": "Tyler Brooks",
        "email": "t.brooks@veteranlawns.com",
        "phone": "410-555-0103",
        "position": "lawn_service",
        "employment_type": "part_time",
        "hire_date": date(2024, 5, 20),
        "hourly_rate": 16.00,
        "authorized_to_work": True,
        "requires_sponsorship": False,
        "work_auth_status": "citizen",
        "status": "active",
    },
    {
        "employee_id": "VLL-000004",
        "name": "Brianna Nguyen",
        "email": "b.nguyen@veteranlawns.com",
        "phone": "410-555-0104",
        "position": "lawn_service",
        "employment_type": "full_time",
        "hire_date": date(2021, 9, 8),
        "hourly_rate": 19.00,
        "authorized_to_work": True,
        "requires_sponsorship": False,
        "work_auth_status": "citizen",
        "status": "active",
        "notes": "Lead crew member, handles equipment maintenance",
    },
    {
        "employee_id": "VLL-000005",
        "name": "James Whitfield",
        "email": "j.whitfield@veteranlawns.com",
        "phone": "410-555-0105",
        "position": "sales",
        "employment_type": "full_time",
        "hire_date": date(2023, 1, 16),
        "hourly_rate": 22.00,
        "authorized_to_work": True,
        "requires_sponsorship": False,
        "work_auth_status": "citizen",
        "status": "active",
    },
    {
        "employee_id": "VLL-000006",
        "name": "Sofia Martinez",
        "email": "s.martinez@veteranlawns.com",
        "phone": "410-555-0106",
        "position": "sales",
        "employment_type": "full_time",
        "hire_date": date(2024, 2, 1),
        "hourly_rate": 21.50,
        "authorized_to_work": True,
        "requires_sponsorship": False,
        "work_auth_status": "permanent_resident",
        "status": "active",
    },
    {
        "employee_id": "VLL-000007",
        "name": "Kevin O'Brien",
        "email": "k.obrien@veteranlawns.com",
        "phone": "410-555-0107",
        "position": "support",
        "employment_type": "full_time",
        "hire_date": date(2022, 11, 7),
        "hourly_rate": 18.00,
        "authorized_to_work": True,
        "requires_sponsorship": False,
        "work_auth_status": "citizen",
        "status": "active",
    },
    {
        "employee_id": "VLL-000008",
        "name": "Aaliyah Washington",
        "email": "a.washington@veteranlawns.com",
        "phone": "410-555-0108",
        "position": "support",
        "employment_type": "part_time",
        "hire_date": date(2025, 6, 10),
        "hourly_rate": 17.00,
        "authorized_to_work": True,
        "requires_sponsorship": False,
        "work_auth_status": "citizen",
        "status": "active",
    },
    {
        "employee_id": "VLL-000009",
        "name": "Raymond Castillo",
        "email": "r.castillo@veteranlawns.com",
        "phone": "410-555-0109",
        "position": "manager",
        "employment_type": "full_time",
        "hire_date": date(2020, 7, 27),
        "hourly_rate": 28.00,
        "authorized_to_work": True,
        "requires_sponsorship": False,
        "work_auth_status": "citizen",
        "status": "active",
        "notes": "Operations manager, oversees field crews",
    },
    {
        "employee_id": "VLL-000010",
        "name": "Priya Patel",
        "email": "p.patel@veteranlawns.com",
        "phone": "410-555-0110",
        "position": "lawn_service",
        "employment_type": "contractor",
        "hire_date": date(2025, 3, 1),
        "hourly_rate": 25.00,
        "authorized_to_work": True,
        "requires_sponsorship": False,
        "work_auth_status": "work_visa",
        "status": "active",
    },
]


async def seed():
    async with AsyncSessionLocal() as db:
        for data in EMPLOYEES:
            emp = Employee(**data)
            db.add(emp)
        await db.commit()
        print(f"Seeded {len(EMPLOYEES)} employees.")


if __name__ == "__main__":
    asyncio.run(seed())
