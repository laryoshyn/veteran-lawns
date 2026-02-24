"""Tiered pricing service — reads/writes rates.json."""

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

RATES_FILE = Path(__file__).parent.parent / "rates.json"


@dataclass
class PriceTier:
    label: str
    min_acres: float
    max_acres: float | None  # None means no upper bound
    price: float | None       # None means quote required
    quote_required: bool


def load_tiers() -> list[PriceTier]:
    """Load pricing tiers from rates.json."""
    try:
        data = json.loads(RATES_FILE.read_text())
        return [
            PriceTier(
                label=t["label"],
                min_acres=t["min_acres"],
                max_acres=t["max_acres"],
                price=t["price"],
                quote_required=t["quote_required"],
            )
            for t in data["tiers"]
        ]
    except Exception:
        logger.exception("Failed to load rates.json — using hardcoded fallback")
        return _fallback_tiers()


def load_rates_raw() -> dict:
    """Return the raw rates.json dict for the admin API."""
    try:
        return json.loads(RATES_FILE.read_text())
    except Exception:
        return {"tiers": [], "last_updated": str(date.today())}


def save_rates(data: dict) -> None:
    """Persist updated rates to rates.json."""
    data["last_updated"] = str(date.today())
    RATES_FILE.write_text(json.dumps(data, indent=2))
    logger.info("Pricing rates updated")


def calculate_price(acres: float) -> tuple[float | None, bool, str]:
    """
    Return (price, quote_required, tier_label) for a given lot size.

    price is None when quote_required is True.
    """
    for tier in load_tiers():
        in_range = acres >= tier.min_acres and (
            tier.max_acres is None or acres < tier.max_acres
        )
        if in_range:
            return tier.price, tier.quote_required, tier.label

    # Fallback — larger than all defined tiers
    return None, True, "Quote Required"


def _fallback_tiers() -> list[PriceTier]:
    return [
        PriceTier("Below 1/2 Acre",  0.0, 0.5,  215.0, False),
        PriceTier("1/2 – 1 Acre",    0.5, 1.0,  230.0, False),
        PriceTier("1 – 1½ Acres",    1.0, 1.5,  315.0, False),
        PriceTier("1½ Acres & Above", 1.5, None, None,  True),
    ]
