"""SQLAlchemy ORM models for users and customers."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from database import Base


class User(Base):
    """User account for authentication and authorization."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="customer")  # "customer", "admin", or "pm"
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

    # FieldRoutes integration
    fieldroutes_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fieldroutes_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Relationship to user
    user: Mapped[User | None] = relationship(back_populates="customers")


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
