"""Zillow property size lookup via RapidAPI."""

import logging

import httpx

from config import get_settings

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    s = get_settings()
    return bool(s.zillow_api_key)


async def fetch_property_size(address: str) -> float | None:
    """
    Look up property lot size from Zillow via RapidAPI.
    Returns lot size in acres, or None if unavailable.
    Never raises — logs errors and returns None.
    """
    s = get_settings()
    if not _is_configured():
        logger.debug("Zillow API not configured — skipping property size lookup")
        return None

    headers = {
        "X-RapidAPI-Key": s.zillow_api_key,
        "X-RapidAPI-Host": s.zillow_api_host,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Step 1: search by address to get zpid
            search = await client.get(
                f"https://{s.zillow_api_host}/propertyExtendedSearch",
                headers=headers,
                params={"location": address, "home_type": "Houses,MultiFamily,Lots"},
            )
            search.raise_for_status()
            props = search.json().get("props", [])
            if not props:
                logger.info(f"Zillow: no results for '{address}'")
                return None

            zpid = props[0].get("zpid")
            if not zpid:
                return None

            # Step 2: get property details for lot size
            detail = await client.get(
                f"https://{s.zillow_api_host}/property",
                headers=headers,
                params={"zpid": zpid},
            )
            detail.raise_for_status()
            data = detail.json()

            lot_value = data.get("lotAreaValue") or data.get("resoFacts", {}).get("lotSize")
            lot_unit = (data.get("lotAreaUnit") or "sqft").lower()

            if lot_value is None:
                logger.info(f"Zillow: no lot size for zpid {zpid}")
                return None

            acres = float(lot_value) if "acre" in lot_unit else round(float(lot_value) / 43560, 4)
            logger.info(f"Zillow: {address} → {acres} acres (zpid={zpid})")
            return acres

    except Exception:
        logger.exception(f"Zillow API error for '{address}'")
        return None
