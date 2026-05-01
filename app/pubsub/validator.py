"""JSON-schema validation helpers for trade pub/sub payloads."""

from typing import Any

from jsonschema import ValidationError, validate

from app.pubsub.schema_loader import load_schema
from app.pubsub.topics import TRADE_EVENT_TYPE, TRADE_EVENT_VERSION

_TRADE_SCHEMA_PATH = f"polymarket/{TRADE_EVENT_TYPE}/v{TRADE_EVENT_VERSION}/schema.json"


def validate_trade_event_payload(payload: dict[str, Any]) -> None:
    """Validate a trade event payload against the bundled local schema."""
    schema = load_schema(_TRADE_SCHEMA_PATH)
    try:
        validate(instance=payload, schema=schema)
    except ValidationError as exc:
        raise ValueError(f"trade event schema validation failed: {exc.message}") from exc