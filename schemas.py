"""Pydantic schemas for request/response validation."""

import re
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# --- Authentication Schemas ---


class UserCreate(BaseModel):
    """Schema for user registration."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """Ensure password has minimum complexity."""
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserLogin(BaseModel):
    """Schema for user login."""

    email: EmailStr
    password: str


class Token(BaseModel):
    """Schema for JWT token response."""

    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Schema for decoded token data."""

    user_id: int | None = None


class UserResponse(BaseModel):
    """Schema for user data in responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    is_active: bool
    email_verified: bool
    created_at: datetime


# --- Quote Schemas ---


class QuoteRequest(BaseModel):
    """Schema for quote estimation request."""

    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    street_address: str = Field(..., min_length=5, max_length=200)
    city: str = Field(..., min_length=2, max_length=100)
    zipcode: str = Field(..., pattern=r"^\d{5}(-\d{4})?$")
    phone: str = Field(..., min_length=10, max_length=20)
    claimed_size: float = Field(..., gt=0, le=100, description="Claimed lawn size in acres")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure name contains only valid characters."""
        if not re.match(r"^[A-Za-z\s\-\.']+$", v):
            raise ValueError("Name contains invalid characters")
        return v.strip()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Ensure phone contains only valid characters."""
        if not re.match(r"^[\d\-\+\(\)\s]+$", v):
            raise ValueError("Invalid phone format")
        return v.strip()

    @field_validator("street_address", "city")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Strip leading/trailing whitespace."""
        return v.strip()


class QuoteResponse(BaseModel):
    """Schema for quote estimation response."""

    model_config = ConfigDict(from_attributes=True)

    customer_id: int
    claimed_size: float
    actual_size: float
    monthly_quote: float | None       # None when quote_required is True
    size_verified: bool = Field(
        description="True if size was verified via Maryland API"
    )
    quote_required: bool = False      # True for lots >= 1.5 acres
    tier_label: str = ""              # e.g. "1 – 1½ Acres"


# --- Customer/Dashboard Schemas ---


class CustomerResponse(BaseModel):
    """Schema for customer data in responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    address: str
    phone: str
    claimed_size: float | None
    actual_size: float | None
    quote: float | None
    purchased: bool
    created_at: datetime
    service_start_date: date | None = None
    service_frequency: str | None = None
    service_status: str | None = None


# --- Payment Schemas ---


class CheckoutResponse(BaseModel):
    """Schema for Stripe checkout session response."""

    checkout_url: str


class WebhookResponse(BaseModel):
    """Schema for webhook response."""

    status: str = "success"


# --- Password Reset Schemas ---


class PasswordResetRequest(BaseModel):
    """Schema for requesting a password reset."""

    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Schema for confirming a password reset with new password."""

    token: str = Field(..., min_length=32)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """Ensure password has minimum complexity."""
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class PasswordChange(BaseModel):
    """Schema for changing password while logged in."""

    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """Ensure password has minimum complexity."""
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


# --- Email Verification Schemas ---


class EmailVerificationRequest(BaseModel):
    """Schema for requesting email verification resend."""

    email: EmailStr


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str


# --- Service Scheduling Schemas (Phase 1) ---


class ServiceFrequency(str, Enum):
    """Service frequency options."""

    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


class ServiceStatus(str, Enum):
    """Service status options."""

    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class ServiceStartRequest(BaseModel):
    """Request to schedule service start date."""

    service_start_date: date
    service_frequency: ServiceFrequency = ServiceFrequency.WEEKLY


class ServiceScheduleResponse(BaseModel):
    """Response for service scheduling."""

    model_config = ConfigDict(from_attributes=True)

    customer_id: int
    service_start_date: date
    service_frequency: str
    service_status: str
    fieldroutes_synced: bool = False


class CustomerWithServiceResponse(BaseModel):
    """Extended customer response with service fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    address: str
    phone: str
    claimed_size: float | None
    actual_size: float | None
    quote: float | None
    purchased: bool
    created_at: datetime
    service_start_date: date | None = None
    service_frequency: str | None = None
    service_status: str = "pending"
    fieldroutes_customer_id: str | None = None


# --- Landscaping Schemas (Phase 2) ---


class ProjectType(str, Enum):
    """Landscaping project types."""

    HARDSCAPE = "hardscape"
    SOFTSCAPE = "softscape"
    DRAINAGE = "drainage"
    IRRIGATION = "irrigation"
    CUSTOM = "custom"


class ProjectScope(str, Enum):
    """Project scope options."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    CUSTOM = "custom"


class BudgetRange(str, Enum):
    """Budget range options."""

    UNDER_5K = "under_5k"
    FROM_5K_TO_15K = "5k_to_15k"
    FROM_15K_TO_30K = "15k_to_30k"
    FROM_30K_TO_50K = "30k_to_50k"
    OVER_50K = "over_50k"


class TimelinePreference(str, Enum):
    """Timeline preference options."""

    ASAP = "asap"
    WITHIN_1_MONTH = "within_1_month"
    WITHIN_3_MONTHS = "within_3_months"
    WITHIN_6_MONTHS = "within_6_months"
    FLEXIBLE = "flexible"


class ProjectStatus(str, Enum):
    """Landscaping project status."""

    INQUIRY = "inquiry"
    PM_SCHEDULED = "pm_scheduled"
    PRD_PENDING = "prd_pending"
    PROPOSAL_SENT = "proposal_sent"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProposalResponse(str, Enum):
    """Customer response to proposal."""

    ACCEPTED = "accepted"
    DECLINED = "declined"
    PENDING = "pending"


class LandscapingInquiryRequest(BaseModel):
    """Request for landscaping inquiry submission."""

    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    street_address: str = Field(..., min_length=5, max_length=200)
    city: str = Field(..., min_length=2, max_length=100)
    zipcode: str = Field(..., pattern=r"^\d{5}(-\d{4})?$")
    phone: str = Field(..., min_length=10, max_length=20)
    project_type: ProjectType
    project_scope: ProjectScope
    design_preference: str | None = Field(None, max_length=100)
    budget_range: BudgetRange | None = None
    timeline_preference: TimelinePreference | None = None
    project_description: str | None = Field(None, max_length=2000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure name contains only valid characters."""
        if not re.match(r"^[A-Za-z\s\-\.']+$", v):
            raise ValueError("Name contains invalid characters")
        return v.strip()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Ensure phone contains only valid characters."""
        if not re.match(r"^[\d\-\+\(\)\s]+$", v):
            raise ValueError("Invalid phone format")
        return v.strip()


class LandscapingOptionsResponse(BaseModel):
    """Available options for landscaping form dropdowns."""

    project_types: list[dict]
    project_scopes: list[dict]
    budget_ranges: list[dict]
    timeline_preferences: list[dict]


class LandscapingInquiryResponse(BaseModel):
    """Response after submitting landscaping inquiry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    address: str
    project_type: str
    project_scope: str
    project_status: str
    created_at: datetime


class PMVisitScheduleRequest(BaseModel):
    """Request to schedule a PM visit."""

    project_id: int
    preferred_date: datetime
    notes: str | None = Field(None, max_length=500)


class PMVisitResponse(BaseModel):
    """Response for PM visit scheduling."""

    model_config = ConfigDict(from_attributes=True)

    project_id: int
    pm_visit_date: datetime
    pm_visit_requested: bool = True
    project_status: str


class PRDUploadRequest(BaseModel):
    """Request to upload PRD content."""

    prd_content: str = Field(..., min_length=10, description="PRD content as JSON string")
    pm_visit_notes: str | None = Field(None, max_length=5000)


class ROMCalculateRequest(BaseModel):
    """Request to calculate ROM estimate."""

    labor_hours: float = Field(..., gt=0)
    materials_cost: float = Field(..., ge=0)
    contingency_percent: float = Field(default=15, ge=0, le=50)


class ROMEstimateResponse(BaseModel):
    """ROM estimate response."""

    labor_hours: float
    materials_cost: float
    labor_cost_low: float
    labor_cost_high: float
    total_estimate_low: float
    total_estimate_high: float


class ProposalSendRequest(BaseModel):
    """Request to send proposal to customer."""

    rom_estimate_low: float = Field(..., gt=0)
    rom_estimate_high: float = Field(..., gt=0)
    rom_labor_hours: float = Field(..., gt=0)
    rom_materials_cost: float = Field(..., ge=0)


class ProposalResponseRequest(BaseModel):
    """Customer's response to proposal."""

    response: ProposalResponse


class LandscapingProjectResponse(BaseModel):
    """Full landscaping project response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    address: str
    phone: str
    lot_size_acres: float | None
    project_type: str
    project_scope: str
    design_preference: str | None
    budget_range: str | None
    timeline_preference: str | None
    project_description: str | None
    pm_visit_requested: bool
    pm_visit_date: datetime | None
    pm_visit_completed: bool
    rom_estimate_low: float | None
    rom_estimate_high: float | None
    proposal_sent: bool
    customer_response: str | None
    project_status: str
    created_at: datetime
