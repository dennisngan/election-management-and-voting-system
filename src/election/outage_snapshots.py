"""Stable identity for a public outage detail and its immutable history."""

import hashlib
import json
from typing import Any

from pydantic import TypeAdapter

_SNAPSHOT_JSON = TypeAdapter(Any)


def outage_snapshot_digest(snapshot: dict[str, Any]) -> str:
    """Match server UTC datetimes to their public JSON representation."""
    payload = json.dumps(
        _SNAPSHOT_JSON.dump_python(snapshot, mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
