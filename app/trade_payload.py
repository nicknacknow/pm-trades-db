"""Helpers for normalizing trade event payloads."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.pubsub.validator import validate_trade_event_payload


def canonical_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def event_id_for_payload(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def parse_trade_timestamp(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_trade_event(payload: dict[str, Any]) -> dict[str, Any]:
    validate_trade_event_payload(payload)

    event_type = str(payload["event_type"])
    event_version = str(payload["event_version"])
    trade = payload["trade"]
    if not isinstance(trade, dict):
        raise TypeError("trade payload must be an object")

    return {
        "event_type": event_type,
        "event_version": event_version,
        "trade": trade,
    }
