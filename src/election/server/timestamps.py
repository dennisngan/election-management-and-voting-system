"""UTC conversion helpers for database values and event input timestamps."""

from datetime import UTC, datetime


def as_utc(value: datetime | None) -> str | None:
    """Serialize a database-naive UTC datetime as a public UTC timestamp."""
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z") if value else None


def stored_time(value: datetime | None) -> datetime | None:
    """Convert an aware input datetime to the database's naive UTC representation."""
    return value.astimezone(UTC).replace(tzinfo=None) if value else None


def utc_time(value: datetime) -> datetime:
    """Normalize an aware event timestamp to UTC, enforcing supported year bounds."""
    try:
        normalized = value.astimezone(UTC)
    except OverflowError:
        raise ValueError("Time is outside the supported UTC range") from None
    if normalized.year < 1000:
        raise ValueError("Time is outside the supported UTC range")
    return normalized
