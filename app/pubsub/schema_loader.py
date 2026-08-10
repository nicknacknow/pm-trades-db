"""Load pub/sub schemas from bundled schema directory."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


@lru_cache(maxsize=32)
def load_schema(relative_path: str) -> dict[str, Any]:
    """Load a schema file from the bundled schemas directory."""
    schema_path = _SCHEMA_DIR / relative_path
    if not schema_path.exists():
        raise FileNotFoundError(f"schema not found at {schema_path}")
    with schema_path.open(encoding="utf-8") as file_handle:
        return json.load(file_handle)