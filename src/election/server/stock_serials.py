"""Serial strings retain their printed form; arithmetic stays in Python integers."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_STOCK_QUANTITY = 9223372036854775807
StockPool = Literal["ordinary", "replacement", "tendered"]
POOLS: tuple[StockPool, ...] = ("ordinary", "replacement", "tendered")


def serial_number(value: str) -> int:
    if not 1 <= len(value) <= 18 or not value.isascii() or not value.isdecimal():
        raise ValueError("Use 1–18 ASCII serial digits")
    return int(value)


class StockRangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pool: StockPool
    serial_from: str = Field(min_length=1, max_length=18)
    serial_to: str = Field(min_length=1, max_length=18)

    @model_validator(mode="after")
    def ordered_serials(self) -> StockRangeInput:
        if serial_number(self.serial_to) < serial_number(self.serial_from):
            raise ValueError("Serial end must not precede its start")
        return self

    @property
    def quantity(self) -> int:
        return serial_number(self.serial_to) - serial_number(self.serial_from) + 1


def pool_totals(ranges: list[StockRangeInput]) -> dict[StockPool, int]:
    totals: dict[StockPool, int] = {pool: 0 for pool in POOLS}
    previous_end = -1
    for row in sorted(ranges, key=lambda row: serial_number(row.serial_from)):
        first, last = serial_number(row.serial_from), serial_number(row.serial_to)
        if first <= previous_end:
            raise ValueError("Received ranges must not overlap, including between pools")
        previous_end = last
        totals[row.pool] += row.quantity
    if not 1 <= sum(totals.values()) <= MAX_STOCK_QUANTITY:
        raise ValueError("Receive at least one paper within the supported quantity bound")
    return totals
