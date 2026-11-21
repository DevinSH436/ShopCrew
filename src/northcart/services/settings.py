"""Store settings editable from the admin panel (announcement bar, contact details...)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from northcart.models import Setting

DEFAULTS: dict[str, Any] = {
    "announcement": "Free delivery on orders above $35 · Use WELCOME10 for 10% off your first order",
    "support_email": "support@northcart.test",
    "support_phone": "1-800-555-0142",
    "tax_id": "12-3456789",
    "company_name": "Northcart, Inc.",
    "company_address": "500 Commerce Street, Suite 400, Columbus, OH 43215",
    "hero_title": "The Big Holiday Sale is live",
    "hero_subtitle": "Up to 60% off on audio, wearables and home essentials. Extra 10% with WELCOME10.",
}


def get(db: Session, key: str) -> Any:
    """One setting (falls back to the default)."""
    row = db.get(Setting, key)
    return row.value if row is not None else DEFAULTS.get(key)


def all_settings(db: Session) -> dict[str, Any]:
    """Every setting, defaults filled in."""
    values = dict(DEFAULTS)
    for row in db.query(Setting).all():
        values[row.key] = row.value
    return values


def set_many(db: Session, values: dict[str, Any]) -> None:
    """Save several settings at once (unknown keys are ignored)."""
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
    db.commit()
