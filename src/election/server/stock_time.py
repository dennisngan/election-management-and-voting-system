"""Event timestamps supported by the stock ledger's UTC MySQL storage."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime


def supported_stock_event_time(value: datetime) -> datetime:
    try:
        normalized = value.astimezone(UTC)
    except OverflowError as error:
        raise ValueError("Event time is outside the supported UTC range") from error
    if normalized.year < 1000:
        raise ValueError("Event time must be in the supported MySQL range")
    return value


StockEventTime = Annotated[AwareDatetime, AfterValidator(supported_stock_event_time)]
