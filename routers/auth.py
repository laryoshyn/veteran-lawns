"""Authentication endpoints: register, login, logout."""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from database import get_db
from models import User
from schemas import Token, UserCreate, UserResponse

logger = logging.getLogger(__name__)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(
    request: Request,
    user_data: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    Register a new user account.

    Rate limited to 3 registrations per minute per IP.
    """
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create new user
    user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        role="customer",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info(f"New user registered: {user.email}")
    return user


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
async def login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """
    Authenticate user and return JWT token.

    Rate limited to 5 attempts per minute per IP to prevent brute force.
    """
    # Find user by email (username field contains email)
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        logger.warning(f"Failed login attempt for: {form_data.username} from {request.client.host}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        logger.warning(f"Login attempt for disabled account: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is disabled",
        )

    # Update last login timestamp
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    # Create access token
    access_token = create_access_token(user_id=user.id)

    logger.info(f"User logged in: {user.email} from {request.client.host}")
    return Token(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get current authenticated user's information."""
    return current_user
