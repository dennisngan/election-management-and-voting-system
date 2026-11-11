"""Shared physical ballot-box reads and public projections."""

from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from election.server.box_models import BallotBox, BoxEvent, BoxMilestone
from election.server.models import Account
from election.server.station_access import station_scope
from election.server.station_models import PollingStation
from election.server.timestamps import as_utc

type MilestoneKind = Literal[
    "conversion_complete", "first_box_opening", "questionable_determination_start"
]


MILESTONE_KINDS = ("conversion_complete", "first_box_opening", "questionable_determination_start")


def box_event_view(row: BoxEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "box_id": row.box_id,
        "revision": row.revision,
        "kind": row.kind,
        "event_at": as_utc(row.event_at),
        "entered_at": as_utc(row.entered_at),
        "actor_id": row.actor_id,
        "reason": row.reason,
    }


def milestone_view(row: BoxMilestone) -> dict[str, Any]:
    return {
        "id": row.id,
        "station_id": row.station_id,
        "kind": row.kind,
        "revision": row.revision,
        "event_at": as_utc(row.event_at),
        "entered_at": as_utc(row.entered_at),
        "actor_id": row.actor_id,
        "reason": row.reason,
        "box_id": row.box_id,
    }


def box_events(db: Session, box_ids: list[int]) -> list[BoxEvent]:
    if not box_ids:
        return []
    return list(
        db.scalars(
            select(BoxEvent)
            .where(BoxEvent.box_id.in_(box_ids))
            .order_by(BoxEvent.box_id, BoxEvent.revision)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def milestone_rows(db: Session, station_id: int) -> list[BoxMilestone]:
    return list(
        db.scalars(
            select(BoxMilestone)
            .where(BoxMilestone.station_id == station_id)
            .order_by(BoxMilestone.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def box_head(db: Session, box: BallotBox, events: list[BoxEvent]) -> dict[str, Any]:
    assert events
    origin = db.get(PollingStation, box.origin_station_id)
    destination = db.get(PollingStation, box.destination_station_id)
    assert origin is not None and destination is not None
    departure = next((row for row in reversed(events) if row.kind.startswith("departure")), None)
    receipt = next((row for row in reversed(events) if row.kind.startswith("receipt")), None)
    return {
        "id": box.id,
        "origin_station_id": box.origin_station_id,
        "destination_station_id": box.destination_station_id,
        "origin": {"id": origin.id, "code": origin.code, "name": origin.name},
        "destination": {
            "id": destination.id,
            "code": destination.code,
            "name": destination.name,
        },
        "mode": box.mode,
        "box_reference": box.box_reference,
        "seal_reference": box.seal_reference,
        "prepared_at": as_utc(box.prepared_at),
        "entered_at": as_utc(box.entered_at),
        "actor_id": box.actor_id,
        "revision": events[-1].revision,
        "status": "received" if receipt else "departed" if departure else "prepared",
        "departure_at": as_utc(departure.event_at) if departure else None,
        "receipt_at": as_utc(receipt.event_at) if receipt else None,
        "departure": box_event_view(departure) if departure else None,
        "receipt": box_event_view(receipt) if receipt else None,
        "last_event": box_event_view(events[-1]),
    }


def box_snapshot(db: Session, actor: Account, station_id: int) -> dict[str, Any]:
    station, constituency, election = station_scope(db, actor, station_id)
    db.scalar(
        select(PollingStation)
        .where(PollingStation.id == station_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    boxes = list(
        db.scalars(
            select(BallotBox)
            .where(
                or_(
                    BallotBox.origin_station_id == station_id,
                    BallotBox.destination_station_id == station_id,
                )
            )
            .order_by(BallotBox.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    events = box_events(db, [box.id for box in boxes])
    milestones = milestone_rows(db, station_id)
    latest = {row.kind: row for row in milestones}
    return {
        "context": {
            "election": {"id": election.id, "name": election.name, "status": election.status},
            "constituency": {
                "id": constituency.id,
                "name": constituency.name,
                "code": constituency.code,
            },
            "station": {
                "id": station.id,
                "name": station.name,
                "code": station.code,
                "counting_mode": station.counting_mode,
                "destination_station_id": station.destination_station_id,
            },
        },
        "items": [
            box_head(db, box, [row for row in events if row.box_id == box.id]) for box in boxes
        ],
        "milestones": [milestone_view(latest[kind]) for kind in MILESTONE_KINDS if kind in latest],
        "milestone_history": [milestone_view(row) for row in milestones],
        "counting_applicable": station.counting_mode == "local",
        "count_completion": None,
    }
