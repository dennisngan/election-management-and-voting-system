"""Pure, precise Hong Kong event-time input and display shared by desktop editors."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

_HKT = ZoneInfo("Asia/Hong_Kong")


def parse_event_time(text: str, original: str | None = None) -> str:
    """Parse local input, retaining saved precision when its displayed minute is unchanged."""
    text = text.strip()
    if not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?",
        text,
    ):
        raise ValueError("Use a local Hong Kong date and time")
    event = datetime.fromisoformat(text).replace(tzinfo=_HKT)
    if original and text == datetime.fromisoformat(original).astimezone(_HKT).strftime(
        "%Y-%m-%d %H:%M"
    ):
        return original
    return event.isoformat()


def format_event_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return "—"
        local = parsed.astimezone(_HKT)
        precision = (
            "microseconds" if local.microsecond else "seconds" if local.second else "minutes"
        )
        return local.isoformat(sep=" ", timespec=precision).removesuffix("+08:00") + " HKT"
    except TypeError, ValueError, OverflowError:
        return "—"
