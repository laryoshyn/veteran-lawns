"""SQLAlchemy ORM models for users and customers."""

from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from database import Base

# Association table — crew ↔ employee (many-to-many)
crew_members = Table(
    "crew_members",
    Base.metadata,
    Column("crew_id", Integer, ForeignKey("crews.id", ondelete="CASCADE"), primary_key=True),
    Column("employee_id", Integer, ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    """User account for authentication and authorization."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="customer")  # "customer", "admin", "pm", or "sales"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationship to customers
    customers: Mapped[list["Customer"]] = relationship(back_populates="user")
    # Relationship to landscaping projects (as PM)
    assigned_projects: Mapped[list["LandscapingProject"]] = relationship(
        back_populates="assigned_pm", foreign_keys="LandscapingProject.assigned_pm_id"
    )


class Customer(Base):
    """Customer quote record."""

    __tablename__ = "customers"
    __table_args__ = (Index("ix_customers_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    claimed_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote: Mapped[float | None] = mapped_column(Float, nullable=True)
    parcel_id: Mapped[str | None] = mapped_column(String(50), nullable=True)  # Maryland API ACCTID
    purchased: Mapped[bool] = mapped_column(Boolean, default=False)
    stripe_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Service scheduling fields (Phase 1)
    service_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    service_frequency: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # weekly, biweekly, monthly
    service_status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, active, paused, cancelled

    # Quote approval (set by admin/sales before sending payment link)
    quote_approved: Mapped[bool] = mapped_column(Boolean, default=False)

    # AI property size lookup (Zillow lot size + satellite grass area)
    lot_size_acres: Mapped[float | None] = mapped_column(Float, nullable=True)
    map_property_size: Mapped[float | None] = mapped_column(Float, nullable=True)

    # FieldRoutes integration
    fieldroutes_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fieldroutes_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Crew assignment
    crew_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("crews.id"), nullable=True)

    # Relationships
    user: Mapped[User | None] = relationship(back_populates="customers")
    crew: Mapped["Crew | None"] = relationship("Crew", back_populates="customers")


class LandscapingProject(Base):
    """Landscaping project inquiry and tracking."""

    __tablename__ = "landscaping_projects"
    __table_args__ = (
        Index("ix_landscaping_projects_user_id", "user_id"),
        Index("ix_landscaping_projects_assigned_pm_id", "assigned_pm_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    assigned_pm_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )

    # Customer info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    parcel_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lot_size_acres: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Project specification (from dropdowns)
    project_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # hardscape, softscape, drainage, irrigation, custom
    project_scope: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # small, medium, large, custom
    design_preference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    budget_range: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timeline_preference: Mapped[str | None] = mapped_column(String(50), nullable=True)
    project_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # PM Visit scheduling
    pm_visit_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    pm_visit_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pm_visit_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    pm_visit_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # PRD (Project Requirements Document) - stored as JSON string
    prd_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    prd_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ROM (Rough Order of Magnitude) T&M Proposal
    rom_estimate_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    rom_estimate_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    rom_labor_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    rom_materials_cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Proposal tracking
    proposal_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    proposal_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    customer_response: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # accepted, declined, pending
    customer_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Project status
    project_status: Mapped[str] = mapped_column(
        String(30), default="inquiry"
    )  # inquiry, pm_scheduled, prd_pending, proposal_sent, accepted, in_progress, completed, cancelled

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    user: Mapped[User | None] = relationship(
        "User", foreign_keys=[user_id]
    )
    assigned_pm: Mapped[User | None] = relationship(
        "User", back_populates="assigned_projects", foreign_keys=[assigned_pm_id]
    )


class Employee(Base):
    """Staff employee record."""

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    employee_id: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)  # e.g. EMP-001
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[str] = mapped_column(String(50), nullable=False)  # lawn_service, sales, support, manager
    employment_type: Mapped[str] = mapped_column(String(20), default="full_time")  # full_time, part_time, contractor
    hire_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    hourly_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, inactive, terminated

    # I-9 work authorization (mirrors JobApplication fields)
    authorized_to_work: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    requires_sponsorship: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    work_auth_status: Mapped[str | None] = mapped_column(String(50), nullable=True)  # citizen, national, permanent_resident, work_visa

    # Sensitive / HR
    ssn: Mapped[str | None] = mapped_column(String(11), nullable=True)  # stored as XXX-XX-XXXX

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Crew memberships
    crews: Mapped[list["Crew"]] = relationship("Crew", secondary=crew_members, back_populates="members")


class JobApplication(Base):
    """Job application submitted via the careers form."""

    __tablename__ = "job_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[str] = mapped_column(String(50), nullable=False)  # lawn_service, sales, support

    # I-9 work authorization fields
    authorized_to_work: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_sponsorship: Mapped[bool] = mapped_column(Boolean, nullable=False)
    work_auth_status: Mapped[str] = mapped_column(String(50), nullable=False)  # citizen, national, permanent_resident, work_visa

    # Optional
    availability_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    desired_hourly_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tracking
    status: Mapped[str] = mapped_column(String(20), default="new")  # new, reviewing, contacted, hired, rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Crew(Base):
    """Service crew — a named group of employees assigned to customer services."""

    __tablename__ = "crews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    crew_id: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)  # CRW-000001
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, inactive
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Many-to-many: crew members (employees)
    members: Mapped[list["Employee"]] = relationship(
        "Employee", secondary=crew_members, back_populates="crews"
    )
    # Ordered list of customer IDs (JSON array) — defines service stop order
    customer_order: Mapped[str | None] = mapped_column(Text, nullable=True)

    # One-to-many: assigned customer services
    customers: Mapped[list["Customer"]] = relationship("Customer", back_populates="crew")
