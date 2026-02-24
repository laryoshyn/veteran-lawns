"""Test fixtures and configuration."""

import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from datetime import date, timedelta

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test environment before importing app
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only-12345678"
os.environ["DEBUG"] = "true"
os.environ["REDIS_URL"] = "memory://"

from database import Base, get_db
from main import app
from models import Customer, LandscapingProject, User
from auth import get_password_hash


# Test database engine
test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    echo=False,
    connect_args={"check_same_thread": False},
)

TestAsyncSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """Override database dependency for testing."""
    async with TestAsyncSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create database tables and provide a session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestAsyncSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sync_client(db_session: AsyncSession) -> TestClient:
    """Create sync test client for simple tests."""
    return TestClient(app)


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user."""
    user = User(
        email="test@example.com",
        hashed_password=get_password_hash("TestPass123"),
        role="customer",
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_admin(db_session: AsyncSession) -> User:
    """Create a test admin user."""
    user = User(
        email="admin@example.com",
        hashed_password=get_password_hash("AdminPass123"),
        role="admin",
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_pm(db_session: AsyncSession) -> User:
    """Create a test PM user."""
    user = User(
        email="pm@example.com",
        hashed_password=get_password_hash("PMPass123"),
        role="pm",
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_customer(db_session: AsyncSession, test_user: User) -> Customer:
    """Create a test customer/quote record."""
    customer = Customer(
        user_id=test_user.id,
        name="Test Customer",
        email="test@example.com",
        address="123 Test St, Bel Air, MD 21014",
        phone="410-555-1234",
        claimed_size=0.5,
        actual_size=0.5,
        quote=215.0,
        parcel_id="TEST123",
        purchased=False,
    )
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)
    return customer


@pytest_asyncio.fixture
async def purchased_customer(db_session: AsyncSession, test_user: User) -> Customer:
    """Create a purchased customer/quote record."""
    customer = Customer(
        user_id=test_user.id,
        name="Purchased Customer",
        email="test@example.com",
        address="456 Test Ave, Bel Air, MD 21014",
        phone="410-555-5678",
        claimed_size=1.0,
        actual_size=1.0,
        quote=430.0,
        parcel_id="TEST456",
        purchased=True,
        stripe_payment_id="cs_test_123",
    )
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)
    return customer


@pytest_asyncio.fixture
async def test_landscaping_project(db_session: AsyncSession) -> LandscapingProject:
    """Create a test landscaping project."""
    project = LandscapingProject(
        name="Test Project",
        email="project@example.com",
        address="789 Test Blvd, Bel Air, MD 21014",
        phone="410-555-9999",
        project_type="hardscape",
        project_scope="medium",
        budget_range="15k_to_30k",
        timeline_preference="within_3_months",
        project_description="Test patio installation",
        project_status="inquiry",
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


def get_auth_headers(user_id: int) -> dict:
    """Generate auth headers for a user."""
    from auth import create_access_token
    token = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}
