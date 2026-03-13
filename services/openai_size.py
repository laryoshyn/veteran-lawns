"""OpenAI-based property size service.

Two-step process:
  1. Web-search Zillow to get the total lot size in acres.
  2. Web-search satellite/aerial imagery to measure the actual grass fraction,
     then compute: grass_area = lot_size × grass_fraction
"""

import asyncio
import logging

from config import get_settings

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    return bool(get_settings().openai_api_key)


def _get_lot_size_sync(address: str) -> float:
    """Step 1: Fetch total lot size from Zillow."""
    from openai import OpenAI
    client = OpenAI(api_key=get_settings().openai_api_key)

    res = client.responses.create(
        model="gpt-4o",
        tools=[{"type": "web_search_preview"}],
        input=(
            f"Find the total lot size for this property: {address}\n"
            f"Check Zillow first, then Redfin, then any public county property records.\n"
            f"If shown in square feet, convert to acres (divide by 43560).\n"
            f"Return ONLY a single decimal number in acres. No text, no units, no explanation."
        ),
    )
    text = res.output_text.strip()
    for ch in ("acres", "acre", "ac", ",", " "):
        text = text.replace(ch, "")
    return float(text.strip())


def _get_grass_fraction_sync(address: str, lot_size: float) -> float:
    """Step 2: Analyse satellite imagery to find the real grass fraction."""
    from openai import OpenAI
    client = OpenAI(api_key=get_settings().openai_api_key)

    res = client.responses.create(
        model="gpt-4o",
        tools=[{"type": "web_search_preview"}],
        input=(
            f"Look at the satellite or aerial view of this property on Google Maps or Bing Maps: {address}\n"
            f"The total lot size is {lot_size:.4f} acres.\n"
            f"Estimate what fraction of the lot is mowable grass or lawn — "
            f"green turf areas only, excluding the house footprint, driveway, patio, "
            f"deck, pool, garden beds, trees, and any other non-grass surfaces.\n"
            f"Return ONLY a decimal number between 0.0 and 1.0 representing the grass fraction. "
            f"No text, no percent sign, no explanation — just the number."
        ),
    )
    text = res.output_text.strip().replace("%", "").replace(",", "").strip()
    fraction = float(text)
    # If model returned a percentage (e.g. 65) instead of a fraction (0.65), normalise it
    if fraction > 1.0:
        fraction = fraction / 100.0
    return max(0.0, min(fraction, 1.0))


async def fetch_property_sizes(address: str) -> tuple[float | None, float | None]:
    """
    Returns (lot_size_acres, grass_area_acres).
    Step 1 — Zillow/Redfin/county lot size.
    Step 2 — satellite imagery grass fraction.
    Both values are None on failure.
    """
    if not _is_configured():
        return None, None

    try:
        lot_size = await asyncio.to_thread(_get_lot_size_sync, address)
        if not lot_size or lot_size <= 0:
            logger.warning(f"Lot size lookup returned nothing for '{address}'")
            return None, None

        grass_fraction = await asyncio.to_thread(_get_grass_fraction_sync, address, lot_size)
        grass_area = round(lot_size * grass_fraction, 4)

        logger.info(
            f"Property '{address}': lot={lot_size} acres, "
            f"grass={grass_fraction:.0%} → {grass_area} acres"
        )
        return round(lot_size, 4), grass_area

    except Exception as e:
        logger.warning(f"OpenAI size lookup failed for '{address}': {e}")
        return None, None


# Convenience wrapper used by quote submission (grass area only)
async def fetch_grass_area(address: str) -> float | None:
    _, grass = await fetch_property_sizes(address)
    return grass


def _route_sync(addresses: list[str]) -> list[int]:
    """Ask GPT-4o to return the optimal driving order as a JSON array of 0-based indices."""
    import json
    from openai import OpenAI
    client = OpenAI(api_key=get_settings().openai_api_key)

    numbered = "\n".join(f"{i}: {addr}" for i, addr in enumerate(addresses))
    res = client.responses.create(
        model="gpt-4o",
        tools=[{"type": "web_search_preview"}],
        input=(
            f"I have a list of service addresses in Harford County, MD that a lawn care crew must visit.\n"
            f"Find the optimal driving route that minimises total travel distance, "
            f"starting from the first address as the depot.\n\n"
            f"Addresses:\n{numbered}\n\n"
            f"Return ONLY a JSON array of the 0-based indices in the optimal visit order. "
            f"Example for 4 stops: [0, 2, 3, 1]\n"
            f"No explanation, no markdown, no extra text — just the JSON array."
        ),
    )
    text = res.output_text.strip()
    # Strip markdown code fences if model wrapped the response
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    order = json.loads(text.strip())
    # Validate: must be a permutation of 0..n-1
    if sorted(order) != list(range(len(addresses))):
        raise ValueError(f"Invalid order returned: {order}")
    return order


async def route_crew_customers(addresses: list[str]) -> list[int]:
    """Return 0-based indices in optimal driving order. Returns identity order on failure."""
    if not _is_configured() or not addresses:
        return list(range(len(addresses)))
    try:
        order = await asyncio.to_thread(_route_sync, addresses)
        logger.info("Auto-route computed for %d addresses: %s", len(addresses), order)
        return order
    except Exception as e:
        logger.warning("Auto-route failed: %s", e)
        return list(range(len(addresses)))
