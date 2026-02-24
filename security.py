"""Security utilities for token generation and input sanitization."""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from config import get_settings

settings = get_settings()

# Token expiration times
PASSWORD_RESET_EXPIRE_HOURS = 24
EMAIL_VERIFICATION_EXPIRE_HOURS = 48


def generate_secure_token(length: int = 32) -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_urlsafe(length)


def generate_password_reset_token() -> tuple[str, datetime]:
    """
    Generate a password reset token with expiration.

    Returns:
        Tuple of (token, expiration_datetime)
    """
    token = generate_secure_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=PASSWORD_RESET_EXPIRE_HOURS)
    return token, expires


def generate_email_verification_token() -> tuple[str, datetime]:
    """
    Generate an email verification token with expiration.

    Returns:
        Tuple of (token, expiration_datetime)
    """
    token = generate_secure_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=EMAIL_VERIFICATION_EXPIRE_HOURS)
    return token, expires


def hash_token(token: str) -> str:
    """
    Hash a token for secure storage.

    Uses HMAC-SHA256 with the application secret key.
    """
    return hmac.new(
        settings.secret_key.encode(),
        token.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_token_hash(token: str, token_hash: str) -> bool:
    """Verify a token against its stored hash."""
    return hmac.compare_digest(hash_token(token), token_hash)


def is_token_expired(expiration: datetime) -> bool:
    """Check if a token has expired."""
    return datetime.now(timezone.utc) > expiration


# --- Input Sanitization ---


def sanitize_html(text: str) -> str:
    """
    Remove HTML tags from text to prevent XSS.

    Note: For display, prefer proper HTML escaping in templates.
    """
    return re.sub(r"<[^>]*>", "", text)


def sanitize_sql_like(text: str) -> str:
    """
    Escape special characters for SQL LIKE queries.

    Use with parameterized queries - this escapes wildcards.
    """
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to prevent path traversal attacks.

    Removes path components and dangerous characters.
    """
    # Remove path separators
    filename = filename.replace("/", "").replace("\\", "")
    # Remove null bytes
    filename = filename.replace("\x00", "")
    # Remove leading/trailing dots and spaces
    filename = filename.strip(". ")
    # Limit length
    return filename[:255] if filename else "unnamed"


def is_safe_url(url: str, allowed_hosts: list[str]) -> bool:
    """
    Check if a URL is safe for redirection.

    Prevents open redirect vulnerabilities.
    """
    if not url:
        return False

    # Allow relative URLs
    if url.startswith("/") and not url.startswith("//"):
        return True

    # Check against allowed hosts
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        return parsed.netloc in allowed_hosts
    except Exception:
        return False


# --- Rate Limiting Helpers ---


def get_client_ip(request: Any) -> str:
    """
    Extract client IP address from request.

    Handles X-Forwarded-For header for reverse proxy setups.
    """
    # Check for forwarded header (from reverse proxy)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take the first IP (original client)
        return forwarded.split(",")[0].strip()

    # Fall back to direct connection
    if request.client:
        return request.client.host

    return "unknown"


# --- Password Validation ---


def check_password_strength(password: str) -> list[str]:
    """
    Check password strength and return list of issues.

    Returns empty list if password meets all requirements.
    """
    issues = []

    if len(password) < 8:
        issues.append("Password must be at least 8 characters")
    if len(password) > 128:
        issues.append("Password must be less than 128 characters")
    if not re.search(r"[A-Z]", password):
        issues.append("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        issues.append("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        issues.append("Password must contain at least one digit")

    return issues


def is_common_password(password: str) -> bool:
    """
    Check if password is in common passwords list.

    This is a basic check - consider using a larger list in production.
    """
    common_passwords = {
        "password", "123456", "12345678", "qwerty", "abc123",
        "monkey", "1234567", "letmein", "trustno1", "dragon",
        "baseball", "iloveyou", "master", "sunshine", "ashley",
        "football", "shadow", "123123", "654321", "superman",
        "qazwsx", "michael", "password1", "password123",
    }
    return password.lower() in common_passwords
