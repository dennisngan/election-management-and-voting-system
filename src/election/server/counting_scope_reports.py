"""Compact frozen received-box scope statements with whole-station source limits."""

import csv
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from io import StringIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.accounting_reports import SUMMARY_FIELDS
from election.server.counting_scope_labels import LABELS
from election.server.counting_scope_models import CountingScopeRevision
from election.server.counting_scopes import scope_at, scope_options, scope_view
from election.server.history_pdf import HistoryTable, history_pdf
from election.server.models import Account
from election.server.stock_reports import ReportLocale
from election.server.turnout_reports import hong_kong_time


def _display(key: str, value: Any, labels: dict[str, str]) -> str:
    if value is None or value == "":
        return labels["not_recorded"]
    if isinstance(value, bool):
        return labels["yes" if value else "no"]
    if key.endswith("_at"):
        return hong_kong_time(value)
    if key in ("status", "p18_status", "mode", "kind", "turnout_provenance"):
        return labels[str(value)]
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else labels["none"]
    return str(value)


def _pairs(data: dict[str, Any], keys: tuple[str, ...], labels: dict[str, str]) -> list[list[str]]:
    return [[labels[key], _display(key, data.get(key), labels)] for key in keys]


def _station(row: dict[str, Any]) -> str:
    return f"#{row['id']} · {row['code']} · {row['name']}"


def _table(title: str, pairs: list[list[str]], labels: dict[str, str]) -> HistoryTable:
    return HistoryTable(title, [[labels["field"], labels["value"]], *pairs], (0.40, 0.60))


def _metadata(report: dict[str, Any]) -> list[list[str]]:
    labels, record = report["labels"], report["record"]
    context = record["context"]
    return [
        [labels["election"], context["election"]["name"]],
        [labels["election_status"], labels[context["election"]["status"]]],
        [labels["constituency"], _station(context["constituency"])],
        [labels["counting_station"], _station(context["station"])],
        *_pairs(
            {**record, "scope_id": record["id"]},
            (
                "scope_id",
                "reference",
                "revision_id",
                "revision",
                "status",
                "is_current",
                "source_current",
                "count_ready",
                "event_at",
                "entered_at",
                "actor_id",
                "submitted_at",
                "submitted_by",
                "notes",
                "amendment_reason",
            ),
            labels,
        ),
        [labels["generated_at"], hong_kong_time(report["generated_at"])],
        [labels["time_basis"], "Asia/Hong_Kong (UTC+08:00)"],
    ]


def _box_tables(record: dict[str, Any], labels: dict[str, str]) -> list[HistoryTable]:
    result = []
    for box in record["box_basis"]:
        title = labels["box_basis"] + f" · #{box['id']} · " + box["box_reference"]
        result.append(
            _table(
                title,
                [
                    *_pairs(
                        {**box, "box_id": box["id"]},
                        (
                            "box_id",
                            "box_reference",
                            "seal_reference",
                            "revision",
                            "status",
                            "mode",
                            "prepared_at",
                            "entered_at",
                            "actor_id",
                        ),
                        labels,
                    ),
                    [labels["origin"], _station(box["origin"])],
                    [labels["destination"], _station(box["destination"])],
                ],
                labels,
            )
        )
        for kind in ("departure", "receipt"):
            event = box[kind]
            rows = (
                _pairs(
                    event,
                    ("id", "revision", "kind", "event_at", "entered_at", "actor_id", "reason"),
                    labels,
                )
                if event
                else [[labels["id"], labels["not_recorded"]]]
            )
            result.append(_table(title + " · " + labels[kind], rows, labels))
    if not result:
        result.append(
            _table(
                labels["box_basis"],
                [
                    [labels["box_id"], labels["scope_boxes_missing"]],
                ],
                labels,
            )
        )
    return result


def _accounting_tables(record: dict[str, Any], labels: dict[str, str]) -> list[HistoryTable]:
    tables = []
    for source in record["accounting_basis"]:
        title = labels["accounting_basis"] + " · " + _station(source["context"]["station"])
        details = {
            **source,
            "p18_id": source["id"],
            "p18_revision": source["revision"],
            "p18_status": source["status"],
            "frozen_p18_source_current": source["source_current"],
            "frozen_p18_approval_valid": source["approval_valid"],
        }
        tables.append(
            _table(
                title,
                [
                    [labels["report_scope"], labels["accounting_note"]],
                    *_pairs(
                        details,
                        (
                            "p18_id",
                            "p18_revision",
                            "p18_status",
                            "frozen_p18_source_current",
                            "frozen_p18_approval_valid",
                            "event_at",
                            "entered_at",
                            "actor_id",
                            "submitted_at",
                            "submitted_by",
                            "approved_at",
                            "approved_by",
                            "notes",
                            "amendment_reason",
                        ),
                        labels,
                    ),
                    *_pairs(source["summary"], SUMMARY_FIELDS, labels),
                ],
                labels,
            )
        )
        turnout = source["turnout"]
        row = turnout["record"]
        frozen_turnout = {
            "frozen_turnout_valid": turnout["approval_valid"],
            "turnout_period": row["period_index"] if row else None,
            "turnout_revision": row["revision"] if row else None,
            "turnout_provenance": row["provenance"] if row else None,
            "supplied_total": row["supplied_cumulative"] if row else None,
            "approved_total": row["derived_cumulative_end"]
            if row and turnout["approval_valid"]
            else None,
        }
        tables.append(
            _table(
                title + " · " + labels["turnout"],
                _pairs(
                    frozen_turnout,
                    (
                        "frozen_turnout_valid",
                        "turnout_period",
                        "turnout_revision",
                        "turnout_provenance",
                        "supplied_total",
                        "approved_total",
                    ),
                    labels,
                ),
                labels,
            )
        )
    return tables


def _tables(report: dict[str, Any]) -> list[HistoryTable]:
    labels, record = report["labels"], report["record"]
    tables = [
        _table(
            labels["readiness"],
            [
                [labels["report_scope"], labels["scope_note"]],
                [labels["coverage"], labels["mixed_note"]],
                *_pairs(
                    record,
                    ("estimated_box_from_stock_quantity", "estimated_box_from_turnout_quantity"),
                    labels,
                ),
            ],
            labels,
        )
    ]
    blocker_rows = []
    for blocker in record["blockers"]:
        identifiers = [
            labels[key] + " " + str(blocker[key])
            for key in ("box_id", "station_id")
            if key in blocker
        ]
        blocker_rows.append([labels[blocker["code"]], "; ".join(identifiers) or labels["none"]])
    tables.append(
        _table(
            labels["blockers"],
            blocker_rows
            or [
                [labels["blocker_none"], labels["none"]],
            ],
            labels,
        )
    )
    for coverage in record["coverage"]:
        title = labels["coverage"] + " · " + _station(coverage["station"])
        tables.append(
            _table(
                title,
                [
                    *_pairs(
                        coverage,
                        ("scope_box_ids", "source_box_ids", "all_source_boxes_in_scope"),
                        labels,
                    ),
                    [
                        labels["coverage"],
                        labels[
                            "full_note" if coverage["all_source_boxes_in_scope"] else "partial_note"
                        ],
                    ],
                ],
                labels,
            )
        )
    tables.extend(_box_tables(record, labels))
    tables.extend(_accounting_tables(record, labels))
    return tables


def _rows(report: dict[str, Any]) -> list[list[str]]:
    result = [[report["title"]], *_metadata(report)]
    for table in _tables(report):
        result += [[], [table.title], *table.rows]
    return result


def _csv(report: dict[str, Any]) -> bytes:
    output = StringIO(newline="")
    csv.writer(output).writerows(_rows(report))
    return output.getvalue().encode("utf-8-sig")


def _pdf(report: dict[str, Any]) -> bytes:
    record, labels = report["record"], report["labels"]
    return history_pdf(
        report["title"],
        _metadata(report),
        _tables(report),
        record["reference"] + " · " + labels["revision"] + " " + str(record["revision"]),
        labels["page"],
    )


def counting_scope_reports_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/counting-scopes/{scope_id}/revisions/{revision}",
        tags=["Counting scope statements"],
    )
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    def projection(
        station_id: int,
        scope_id: int,
        revision: int,
        locale: ReportLocale,
        db: Session,
        actor: Account,
    ) -> dict[str, Any]:
        options = scope_options(db, actor, station_id)
        scope = scope_at(db, station_id, scope_id)
        row = db.scalar(
            select(CountingScopeRevision)
            .where(
                CountingScopeRevision.scope_id == scope_id,
                CountingScopeRevision.revision == revision,
            )
            .with_for_update()
        )
        if row is None:
            raise HTTPException(404, detail={"code": "counting_scope_not_found"})
        return {
            "station_id": station_id,
            "scope_id": scope_id,
            "revision": revision,
            "locale": locale,
            "record": scope_view(db, scope, row, options["boxes"]),
            "labels": LABELS[locale],
            "title": LABELS[locale]["title"],
            "generated_at": timestamp().replace(tzinfo=UTC),
            "generation_timezone": "Asia/Hong_Kong",
        }

    @router.get("/statement")
    def statement(
        station_id: int,
        scope_id: int,
        revision: Annotated[int, Path(ge=1)],
        db: Database,
        actor: Actor,
        locale: ReportLocale = "tc",
    ) -> dict[str, Any]:
        report = projection(station_id, scope_id, revision, locale, db, actor)
        report["metadata"] = _metadata(report)
        report["tables"] = [
            {"title": table.title, "rows": table.rows, "column_widths": table.widths}
            for table in _tables(report)
        ]
        report["preview_lines"] = [" · ".join(row) for row in _rows(report)]
        return report

    @router.get("/statement.csv")
    def statement_csv(
        station_id: int,
        scope_id: int,
        revision: Annotated[int, Path(ge=1)],
        db: Database,
        actor: Actor,
        locale: ReportLocale = "tc",
    ) -> Response:
        report = projection(station_id, scope_id, revision, locale, db, actor)
        filename = f"scope-{scope_id}-revision-{revision}-{locale}.csv"
        return Response(
            _csv(report),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/statement.pdf")
    def statement_pdf(
        station_id: int,
        scope_id: int,
        revision: Annotated[int, Path(ge=1)],
        db: Database,
        actor: Actor,
        locale: ReportLocale = "tc",
    ) -> Response:
        report = projection(station_id, scope_id, revision, locale, db, actor)
        filename = f"scope-{scope_id}-revision-{revision}-{locale}.pdf"
        return Response(
            _pdf(report),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
