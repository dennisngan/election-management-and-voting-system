"""Selected P(18) statements preserve frozen quantities and source revisions."""

import csv
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from io import StringIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy.orm import Session

from election.server.accounting import accounting_record, accounting_scope, record_view
from election.server.accounting_labels import LABELS
from election.server.history_pdf import HistoryTable, history_pdf
from election.server.models import Account
from election.server.stock_reports import ReportLocale
from election.server.turnout_reports import hong_kong_time, source_basis_tables

SUMMARY_FIELDS = (
    "received_quantity", "ordinary_received_quantity", "ordinary_central_unissued_quantity",
    "ordinary_at_desks_quantity", "replacement_unissued_quantity", "tendered_unissued_quantity",
    "ordinary_issued_quantity", "replacement_issued_quantity", "spoilt_original_quantity",
    "tendered_issued_quantity", "retrieved_refused_quantity", "retrieved_found_quantity",
    "retrieved_held_quantity", "retrieved_unused_quantity", "never_issued_quantity",
    "estimated_box_from_stock_quantity", "estimated_box_from_turnout_quantity",
    "observed_counted_quantity",
)
STOCK_FIELDS = (
    "ordinary_allocated_quantity", "ordinary_returned_quantity", "ordinary_net_allocated_quantity",
    "ordinary_remaining_quantity", "ordinary_issued_quantity",
)
SPECIAL_FIELDS = (
    "received_quantity", "ordinary_issued_quantity", "replacement_issued_quantity",
    "spoilt_original_quantity", "tendered_issued_quantity", "retrieved_refused_quantity",
    "retrieved_found_quantity", "retrieved_held_quantity", "retrieved_unused_quantity",
    "ordinary_unissued_quantity", "replacement_unissued_quantity", "tendered_unissued_quantity",
    "never_issued_quantity", "estimated_box_papers_quantity",
)
TURNOUT_FIELDS = (
    "id", "period_index", "revision", "status", "schedule_revision", "start_at", "end_at",
    "supplied_hourly", "supplied_cumulative", "derived_hourly", "derived_cumulative_start",
    "derived_cumulative_end", "provenance", "source_context", "event_at", "entered_at",
    "actor_id", "submitted_at", "submitted_by", "approved_at", "approved_by",
    "amendment_reason", "basis_predecessor_record_id", "basis_predecessor_revision",
)


def _display(key: str, value: Any, labels: dict[str, str]) -> str:
    if value is None or value == "":
        return labels["not_recorded"]
    if isinstance(value, bool):
        return labels["yes" if value else "no"]
    if key.endswith("_at"):
        return hong_kong_time(value)
    if key in ("status", "provenance", "pool", "kind"):
        return labels[str(value)]
    return str(value)


def _pairs(data: dict[str, Any], fields: tuple[str, ...],
           labels: dict[str, str]) -> list[list[str]]:
    return [[labels[key], _display(key, data.get(key), labels)] for key in fields]


def _table(title: str, rows: list[list[str]], labels: dict[str, str]) -> HistoryTable:
    return HistoryTable(
        title, [[labels["field"], labels["value"]], *rows], (0.42, 0.58),
    )


def _metadata(report: dict[str, Any]) -> list[list[str]]:
    labels, record, scope = report["labels"], report["record"], report["scope"]
    rows = [
        [labels["election"], scope["election"]["name"]],
        [labels["election_status"], labels[scope["election"]["status"]]],
        [labels["constituency"], scope["constituency"]["code"] + " · "
         + scope["constituency"]["name"]],
        [labels["station"], scope["station"]["code"] + " · " + scope["station"]["name"]],
        [labels["revision_state"], labels[report["revision_state"]]],
    ]
    rows += _pairs(record, (
        "id", "revision", "status", "event_at", "entered_at", "actor_id", "submitted_at",
        "submitted_by", "approved_at", "approved_by", "source_current", "approval_valid",
        "notes", "amendment_reason",
    ), labels)
    rows += [
        [labels["generated_at"], hong_kong_time(report["generated_at"])],
        [labels["time_basis"], "Asia/Hong_Kong (UTC+08:00)"],
    ]
    return rows


def _snapshot_tables(snapshot: dict[str, Any], labels: dict[str, str],
                     title: str) -> list[HistoryTable]:
    identity = title + " · " + labels["id"] + " " + str(snapshot["id"]) + " · " \
        + labels["revision"] + " " + str(snapshot["revision"])
    tables = [_table(identity, _pairs(snapshot, (
        "id", "revision", "event_at", "entered_at", "actor_id", *STOCK_FIELDS,
    ), labels), labels)]
    for basis, key in (("receipt_basis", "receipt_id"), ("allocation_basis", "allocation_id"),
                       ("return_basis", "return_id")):
        rows = [[str(row[key]), str(row["revision"])] for row in snapshot[basis]]
        tables.append(HistoryTable(
            identity + " · " + labels[basis], [[labels[key], labels["revision"]], *rows],
            (0.50, 0.50), labels["none"] if not rows else "", split_in_row=False,
        ))
    for counter in snapshot["counters"]:
        details = counter["counter"]
        counter_title = identity + " · " + labels["counter"] + " " \
            + details["code"] + " · " + details["name"]
        tables.append(_table(counter_title, [
            [labels["reporting_status"], labels["reported" if counter["reported"]
                                               else "not_reported"]],
            *_pairs(counter, STOCK_FIELDS, labels),
        ], labels))
        for key, ranges in (("remaining_ranges", counter["ranges"]),
                            ("issued_ranges", counter["issued_ranges"])):
            tables.append(HistoryTable(
                counter_title + " · " + labels[key],
                [[labels[name] for name in ("series", "serial_from", "serial_to", "quantity")]]
                + [[line["series"], line["serial_from"], line["serial_to"], str(line["quantity"])]
                   for line in ranges or []],
                (0.40, 0.22, 0.22, 0.16),
                labels["not_reported"] if ranges is None
                else labels["empty_ranges"] if not ranges else "", split_in_row=False,
            ))
    return tables


def _special_tables(special: dict[str, Any], labels: dict[str, str]) -> list[HistoryTable]:
    title = labels["special_papers"]
    tables = [_table(title, _pairs(special, (
        "id", "revision", "event_at", "entered_at", "actor_id", "reason",
        "stock_snapshot_id", "stock_snapshot_revision",
    ), labels), labels)]
    for series in special["series"]:
        tables.append(_table(title + " · " + labels["series"] + " " + series["series"],
                             _pairs(series, SPECIAL_FIELDS, labels), labels))
    ranges = special["received_ranges"]
    tables.append(HistoryTable(
        labels["received_ranges"],
        [[labels[key] for key in ("receipt_id", "revision", "series", "pool", "serial_from",
                                 "serial_to", "quantity")]]
        + [[str(line["receipt_id"]), str(line["revision"]), line["series"], labels[line["pool"]],
            line["serial_from"], line["serial_to"], str(line["quantity"])] for line in ranges],
        (0.09, 0.08, 0.25, 0.12, 0.17, 0.17, 0.12),
        labels["none"] if not ranges else "", split_in_row=False,
    ))
    return tables


def _turnout_tables(turnout: dict[str, Any], labels: dict[str, str]) -> list[HistoryTable]:
    row = turnout["record"]
    details = [
        [labels["frozen_turnout_approval"], _display("", turnout["approval_valid"], labels)],
        [labels["schedule_revision"], _display("", turnout["schedule_revision"], labels)],
    ]
    if row is None:
        return [_table(labels["turnout"], [*details, [labels["id"], labels["not_recorded"]]],
                       labels)]
    tables = [_table(labels["turnout"], [*details, *_pairs(row, TURNOUT_FIELDS, labels)], labels)]
    tables.extend(source_basis_tables(row, labels))
    basis = row.get("source_basis")
    if basis:
        for key, title in (("activation_stock_snapshot", "activation_stock_snapshot"),
                           ("stock_snapshot", "endpoint_stock_snapshot")):
            tables.extend(_snapshot_tables(basis[key], labels, labels[title]))
        for event in basis.get("source_events", []):
            event_title = labels["source_events"] + " · " + labels[event["kind"]] + " " \
                + str(event["id"]) + " · " + labels["revision"] + " " + str(event["revision"])
            tables.append(_table(event_title, _pairs(event, (
                "id", "revision", "event_at", "cumulative_quantity", "source_context", "reason",
                "approved_at", "approved_by", "stock_snapshot_id", "stock_snapshot_revision",
            ), labels), labels))
            tables.extend(_snapshot_tables(event["stock_snapshot"], labels, event_title))
    return tables


def _tables(report: dict[str, Any]) -> list[HistoryTable]:
    labels, record = report["labels"], report["record"]
    tables = [_table(labels["summary"], [
        [labels["report_scope"], labels["scope_note"]],
        [labels["observed_counted_quantity"], labels["estimate_note"]],
        *_pairs(record["summary"], SUMMARY_FIELDS, labels),
    ], labels)]
    tables.extend(_snapshot_tables(record["stock_snapshot"], labels, labels["stock_snapshot"]))
    tables.extend(_special_tables(record["special_papers"], labels))
    tables.extend(_turnout_tables(record["turnout"], labels))
    return tables


def _rows(report: dict[str, Any]) -> list[list[str]]:
    rows = [[report["title"]], *_metadata(report)]
    for table in _tables(report):
        rows += [[], [table.title], *table.rows]
        if table.empty_message:
            rows.append([table.empty_message])
    return rows


def _csv(report: dict[str, Any]) -> bytes:
    output = StringIO(newline="")
    csv.writer(output).writerows(_rows(report))
    return output.getvalue().encode("utf-8-sig")


def _pdf(report: dict[str, Any]) -> bytes:
    labels = report["labels"]
    footer = report["scope"]["station"]["code"] + " · P(18) · " \
        + labels["revision"] + " " + str(report["revision"])
    return history_pdf(report["title"], _metadata(report), _tables(report), footer, labels["page"])


def accounting_reports_router(
    database: Callable[[], Generator[Session]], ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/accounting/revisions/{revision}",
        tags=["P(18) statements"],
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    def projection(station_id: int, revision: int, locale: ReportLocale,
                   db: Session, actor: Account) -> dict[str, Any]:
        scope = accounting_scope(db, actor, station_id)
        row = accounting_record(db, station_id, revision)
        if row is None:
            raise HTTPException(404, detail={"code": "accounting_not_found"})
        current = accounting_record(db, station_id)
        assert current is not None
        record = record_view(db, row)
        return {
            "station_id": station_id, "revision": revision, "locale": locale,
            "scope": record.get("context", scope), "title": LABELS[locale]["title"],
            "labels": LABELS[locale], "record": record,
            "revision_state": "current" if current.revision == revision else "historical",
            "generated_at": timestamp().replace(tzinfo=UTC),
            "generation_timezone": "Asia/Hong_Kong",
        }

    @router.get("/statement")
    def statement(
        station_id: int, revision: Annotated[int, Path(ge=1)],
        db: Database, actor: Ready, locale: ReportLocale = "tc",
    ) -> dict[str, Any]:
        report = projection(station_id, revision, locale, db, actor)
        return {**report, "preview_lines": [" · ".join(row) for row in _rows(report)]}

    @router.get("/statement.csv")
    def statement_csv(
        station_id: int, revision: Annotated[int, Path(ge=1)],
        db: Database, actor: Ready, locale: ReportLocale = "tc",
    ) -> Response:
        report = projection(station_id, revision, locale, db, actor)
        filename = f"p18-station-{station_id}-r{revision}-{locale}.csv"
        return Response(_csv(report), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @router.get("/statement.pdf")
    def statement_pdf(
        station_id: int, revision: Annotated[int, Path(ge=1)],
        db: Database, actor: Ready, locale: ReportLocale = "tc",
    ) -> Response:
        report = projection(station_id, revision, locale, db, actor)
        filename = f"p18-station-{station_id}-r{revision}-{locale}.pdf"
        return Response(_pdf(report), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    return router
