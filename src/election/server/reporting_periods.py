"""Pure schedule-anchored period boundaries shared by operational reports."""

from datetime import datetime, timedelta

from election.server.lifecycle_models import ElectionSchedule


def period_count(schedule: ElectionSchedule) -> int:
    span = schedule.planned_closing_at - schedule.planned_opening_at
    microseconds = (span.days * 86400 + span.seconds) * 1_000_000 + span.microseconds
    interval = schedule.reporting_interval_minutes * 60 * 1_000_000
    return (microseconds + interval - 1) // interval


def period_bounds(schedule: ElectionSchedule, index: int) -> tuple[datetime, datetime]:
    if index < 1 or index > period_count(schedule):
        raise IndexError("Reporting period is outside the configured schedule")
    step = timedelta(minutes=schedule.reporting_interval_minutes)
    start = schedule.planned_opening_at + (index - 1) * step
    # Cap the addition at closing so the final partial period cannot overflow.
    return start, start + min(step, schedule.planned_closing_at - start)
