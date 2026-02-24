"""Maryland Property Data API client for parcel size lookup."""

import logging
from typing import NamedTuple

import httpx

logger = logging.getLogger(__name__)

# Maryland GeoData API endpoint
MARYLAND_API_URL = (
    "https://geodata.md.gov/imap/rest/services/"
    "PlanningCadastre/MD_PropertyData/MapServer/0/query"
)

# Harford County jurisdiction code
HARFORD_COUNTY_CODE = "HARF"

# Timeout for API requests (seconds)
REQUEST_TIMEOUT = 10.0


class ParcelInfo(NamedTuple):
    """Property parcel information from Maryland API."""

    acctid: str | None
    address: str | None
    acres: float | None
    owner: str | None


async def fetch_parcel_by_address(
    street_address: str,
    city: str,
    zipcode: str,
) -> ParcelInfo | None:
    """
    Fetch parcel information from Maryland Property Data API.

    Args:
        street_address: Street address (e.g., "123 Main St")
        city: City name
        zipcode: ZIP code (5 digits)

    Returns:
        ParcelInfo if found, None if not found or API error
    """
    # Build the WHERE clause using parameterized approach
    # The API uses SQL-like syntax but we sanitize inputs
    sanitized_address = _sanitize_input(street_address.upper())
    sanitized_city = _sanitize_input(city.upper())
    sanitized_zip = _sanitize_input(zipcode[:5])

    where_clause = (
        f"JURSCODE = '{HARFORD_COUNTY_CODE}' AND "
        f"PREMADDR LIKE '%{sanitized_address}%' AND "
        f"RESICITY = '{sanitized_city}' AND "
        f"RESIZIPCODE LIKE '{sanitized_zip}%'"
    )

    params = {
        "where": where_clause,
        "outFields": "ACCTID,PREMADDR,ACRES,OWNNAME1",
        "returnGeometry": "false",
        "f": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(MARYLAND_API_URL, params=params)
            response.raise_for_status()
            data = response.json()

        features = data.get("features", [])
        if not features:
            logger.info(f"No parcel found for: {street_address}, {city}, {zipcode}")
            return None

        # Return the first matching parcel
        attrs = features[0].get("attributes", {})
        return ParcelInfo(
            acctid=attrs.get("ACCTID"),
            address=attrs.get("PREMADDR"),
            acres=attrs.get("ACRES"),
            owner=attrs.get("OWNNAME1"),
        )

    except httpx.TimeoutException:
        logger.warning(f"Maryland API timeout for: {street_address}")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"Maryland API HTTP error: {e.response.status_code}")
        return None
    except Exception as e:
        logger.exception(f"Maryland API error: {e}")
        return None


async def fetch_actual_size(
    street_address: str,
    city: str,
    zipcode: str,
) -> tuple[float | None, str | None]:
    """
    Fetch the actual parcel size in acres from Maryland API.

    Args:
        street_address: Street address
        city: City name
        zipcode: ZIP code

    Returns:
        Tuple of (acres, parcel_id) or (None, None) if not found
    """
    parcel = await fetch_parcel_by_address(street_address, city, zipcode)
    if parcel and parcel.acres:
        return parcel.acres, parcel.acctid
    return None, None


def _sanitize_input(value: str) -> str:
    """
    Sanitize input for use in API query.

    Removes characters that could be used for injection.
    """
    # Remove single quotes, semicolons, and other SQL-sensitive characters
    dangerous_chars = ["'", '"', ";", "--", "/*", "*/", "\\"]
    result = value
    for char in dangerous_chars:
        result = result.replace(char, "")
    return result.strip()
