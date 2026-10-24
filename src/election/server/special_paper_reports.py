"""Statements of selected saved special-paper observations and their frozen sources."""

import csv
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from io import StringIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.models import Account
from election.server.special_paper_labels import LABELS
from election.server.special_paper_models import SpecialPaperRevision, SpecialPaperSnapshot
from election.server.special_papers import QUANTITIES, special_paper_view
from election.server.stock import stock_scope
from election.server.stock_reports import ReportLocale, hong_kong_time


def _metadata_rows(projection: dict[str, Any]) -> list[list[str]]:
    labels, scope, snapshot = projection["labels"], projection["scope"], projection["items"][0]
    metadata = [
        ("election", scope["election"]["name"]),
        ("election_status", labels[scope["election"]["status"]]),
        ("constituency", scope["constituency"]["code"] + " · " + scope["constituency"]["name"]),
        ("station", scope["station"]["code"] + " · " + scope["station"]["name"]),
        ("report_scope", labels[projection["report_scope"]]),
        ("revision_state", labels[projection["revision_state"]]),
        ("snapshot_id", str(snapshot["id"])),
        ("revision", str(snapshot["revision"])),
        ("status", labels[snapshot["status"]]),
        ("provenance", labels["stock_derived"]),
        ("event_at", hong_kong_time(snapshot["event_at"])),
        ("stock_snapshot_id", str(snapshot["stock_snapshot_id"])),
        ("stock_snapshot_revision", str(snapshot["stock_snapshot_revision"])),
        ("stock_snapshot_event_at", hong_kong_time(
            datetime.fromisoformat(snapshot["stock_snapshot_event_at"])
        )),
        ("entered_at", hong_kong_time(snapshot["entered_at"])),
        ("actor_id", str(snapshot["actor_id"])),
        ("reason", snapshot["reason"] or labels["none"]),
        ("generated_at", hong_kong_time(projection["generated_at"])),
        ("time_basis", "Asia/Hong_Kong (UTC+08:00)"),
    ]
    return [[labels[key], value] for key, value in metadata]


def _report_rows(projection: dict[str, Any]) -> list[list[str]]:
    labels, snapshot = projection["labels"], projection["items"][0]
    rows = [[projection["title"]], *_metadata_rows(projection)]
    rows.extend([[labels[key]] for key in ("scope_note", "provenance_note", "estimate_note")])
    rows.extend([[], [labels["summary"]]])
    rows.extend([labels[key], str(snapshot[key])] for key in QUANTITIES)
    for series in snapshot["series"]:
        rows.extend([[], [labels["series"], series["series"]]])
        rows.extend([labels[key], str(series[key])] for key in QUANTITIES)
    rows.extend([[], [labels["receipt_basis"]], [labels["receipt_id"], labels["revision"]]])
    rows.extend([str(row["receipt_id"]), str(row["revision"])]
                for row in snapshot["receipt_basis"])
    if not snapshot["receipt_basis"]:
        rows.append([labels["none"]])
    range_keys = (
        "receipt_id", "revision", "series", "pool", "serial_from", "serial_to", "quantity",
    )
    rows.extend([[], [labels["received_ranges"]], [labels[key] for key in range_keys]])
    for row in snapshot["received_ranges"]:
        rows.append([labels[row[key]] if key == "pool" else str(row[key]) for key in range_keys])
    if not snapshot["received_ranges"]:
        rows.append([labels["none"]])
    return rows


def _csv_report(projection: dict[str, Any]) -> bytes:
    output = StringIO(newline="")
    csv.writer(output).writerows(_report_rows(projection))
    return output.getvalue().encode("utf-8-sig")


def special_paper_reports_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/special-papers",
        tags=["Special-paper statements"],
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    @router.get("/statement")
    def statement(
        station_id: int, db: Database, actor: Ready,
        snapshot_id: Annotated[int, Query(ge=1)],
        revision: Annotated[int, Query(ge=1)],
        locale: ReportLocale = "tc",
    ) -> dict[str, Any]:
        stock_scope(db, actor, station_id)
        head = db.scalar(select(SpecialPaperSnapshot).where(
            SpecialPaperSnapshot.id == snapshot_id, SpecialPaperSnapshot.station_id == station_id,
        ))
        if head is None:
            raise HTTPException(404, detail={"code": "special_paper_not_found"})
        row = db.scalar(select(SpecialPaperRevision).where(
            SpecialPaperRevision.snapshot_id == snapshot_id,
            SpecialPaperRevision.revision == revision,
        ))
        if row is None:
            raise HTTPException(404, detail={"code": "special_paper_not_found"})
        snapshot = special_paper_view(row, station_id)
        projection = {
            "scope": snapshot["scope"], "items": [snapshot], "availability": None,
            "report_scope": "snapshot_revision", "snapshot_id": snapshot_id, "revision": revision,
            "revision_state": "current" if head.revision == revision else "historical",
            "locale": locale, "title": LABELS[locale]["title"], "labels": LABELS[locale],
            "generated_at": timestamp().replace(tzinfo=UTC),
            "generation_timezone": "Asia/Hong_Kong",
        }
        return {
            **projection, "preview_lines": [" · ".join(row) for row in _report_rows(projection)],
        }

    @router.get("/statement.csv")
    def statement_csv(
        station_id: int, db: Database, actor: Ready,
        snapshot_id: Annotated[int, Query(ge=1)],
        revision: Annotated[int, Query(ge=1)],
        locale: ReportLocale = "tc",
    ) -> Response:
        projection = statement(station_id, db, actor, snapshot_id, revision, locale)
        filename = f"special-papers-{snapshot_id}-r{revision}-{locale}.csv"
        return Response(
            _csv_report(projection), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
