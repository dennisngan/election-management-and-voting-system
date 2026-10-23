"""Pure, precise Hong Kong event-time display shared by desktop editors."""

from datetime import datetime
from zoneinfo import ZoneInfo


def format_event_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return "—"
        local = parsed.astimezone(ZoneInfo("Asia/Hong_Kong"))
        precision = (
            "microseconds" if local.microsecond else "seconds" if local.second else "minutes"
        )
        return local.isoformat(sep=" ", timespec=precision).removesuffix("+08:00") + " HKT"
    except TypeError, ValueError, OverflowError:
        return "—"
