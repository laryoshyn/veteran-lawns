"""Business settings — stored in business_settings.json, editable from admin panel."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SETTINGS_FILE = Path(__file__).parent.parent / "business_settings.json"

DEFAULTS: dict = {
    "business_name": "Veteran Lawns & Landscapes",
    "business_phone": "",
    "business_email": "",
    "service_area": "Harford County, MD",
    "business_hours": "Mon–Fri 7am–5pm",
    "service_lead_days": 3,
    "labor_rate_standard": 45.0,
    "labor_rate_pm": 75.0,
    "labor_rate_support": 35.0,
}


def load_business_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            return {**DEFAULTS, **data}
        except Exception:
            logger.exception("Failed to load business_settings.json — using defaults")
    return DEFAULTS.copy()


def save_business_settings(data: dict) -> None:
    allowed = set(DEFAULTS.keys())
    clean = {k: v for k, v in data.items() if k in allowed}
    SETTINGS_FILE.write_text(json.dumps(clean, indent=2))
    logger.info("Business settings saved")
