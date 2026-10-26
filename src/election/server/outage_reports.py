"""Human-readable statements for immutable application-outage history."""

import csv
from collections.abc import Callable, Generator
from datetime import datetime
from io import StringIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from election.outage_snapshots import outage_snapshot_digest
from election.server.history_pdf import HistoryTable, history_pdf
from election.server.models import Account
from election.server.outage_report_labels import OUTAGE_REPORT_LABELS
from election.server.outages import read_outage_snapshot
from election.server.stock import stock_scope
from election.server.stock_reports import ReportLocale
from election.server.turnout_reports import hong_kong_time

_TARGET_KEYS = ("scope_id", "round_id", "period_index", "counter_id", "allocation_id")
_TARGET_COLUMN = {
    "scope_id": "scope_id",
    "round_id": "round_id",
    "period_index": "period_index",
    "counter_id": "counter_id",
    "allocation_id": "allocation_id",
}
_COUNT_F1_QUANTITIES = (
    "questionable_quantity",
    "actual_counted_quantity",
    "initial_valid_quantity",
    "clearly_invalid_quantity",
    "initial_accounted_quantity",
)
_COUNT_F4_QUANTITIES = (
    "accepted_questionable_quantity",
    "rejected_questionable_quantity",
    "final_valid_quantity",
    "final_invalid_quantity",
    "final_accounted_quantity",
)
_TURNOUT_QUANTITIES = (
    "supplied_hourly",
    "supplied_cumulative",
    "derived_hourly",
    "derived_cumulative_start",
    "derived_cumulative_end",
)


def _display(value: Any, labels: dict[str, str], *, quantity: bool = False) -> str:
    if value is None:
        return labels["not_observed"] if quantity else labels["none"]
    if type(value) is bool:
        return labels["yes"] if value else labels["no"]
    if isinstance(value, (str, int)):
        return str(value)
    return labels["none"]


def _time(value: Any, labels: dict[str, str]) -> str:
    if value is None:
        return labels["none"]
    return hong_kong_time(value)


def _target_text(target: Any, labels: dict[str, str]) -> str:
    if not isinstance(target, dict):
        return labels["none"]
    values = [
        labels[_TARGET_COLUMN[key]] + " " + str(target[key])
        for key in _TARGET_KEYS
        if key in target and target[key] is not None
    ]
    return " · ".join(values) or labels["none"]


def _canonical_record(paper: dict[str, Any]) -> dict[str, Any]:
    reentry = paper.get("reentry")
    receipt = reentry.get("record") if isinstance(reentry, dict) else None
    if not isinstance(receipt, dict):
        return {}
    nested = receipt.get("record")
    return nested if isinstance(nested, dict) else receipt


def _receipt_quantities(
    paper: dict[str, Any], labels: dict[str, str], locale: ReportLocale
) -> list[tuple[str, str]]:
    record = _canonical_record(paper)
    rows: list[tuple[str, str]] = []
    workflow = paper.get("workflow")
    if workflow == "count":
        for candidate in record.get("candidate_votes", []):
            if isinstance(candidate, dict):
                name = candidate.get("name") or (
                    labels["candidate"] + " " + str(candidate.get("candidate_id", ""))
                )
                rows.append(
                    (
                        labels["count_candidates"] + " · " + str(name),
                        _display(candidate.get("quantity"), labels, quantity=True),
                    )
                )
        for invalid in record.get("invalid_papers", []):
            if isinstance(invalid, dict):
                reason = invalid.get(f"label_{locale}") or invalid.get("reason_id")
                rows.append(
                    (
                        labels["invalid_papers"] + " · " + str(reason),
                        _display(invalid.get("quantity"), labels, quantity=True),
                    )
                )
        for key in _COUNT_F1_QUANTITIES:
            if key in record:
                rows.append(
                    (
                        labels["count_f1"] + " · " + labels[key],
                        _display(record[key], labels, quantity=True),
                    )
                )
        f2 = record.get("f2")
        if isinstance(f2, dict):
            for entries_key, heading in (
                ("accepted_votes", labels["count_candidates"]),
                ("rejected_papers", labels["invalid_papers"]),
            ):
                for entry in f2.get(entries_key, []):
                    if isinstance(entry, dict):
                        identity = (
                            entry.get("name")
                            or entry.get("label")
                            or entry.get(f"label_{locale}")
                            or entry.get("candidate_id", entry.get("reason_id", ""))
                        )
                        rows.append(
                            (
                                labels["count_f2"] + " · " + heading + " · " + str(identity),
                                _display(entry.get("quantity"), labels, quantity=True),
                            )
                        )
        for key in _COUNT_F4_QUANTITIES:
            if key in record:
                rows.append(
                    (
                        labels["count_f4"] + " · " + labels[key],
                        _display(record[key], labels, quantity=True),
                    )
                )
    elif workflow == "turnout":
        for key in _TURNOUT_QUANTITIES:
            rows.append((labels[key], _display(record.get(key), labels, quantity=True)))
    elif workflow == "allocation":
        rows.extend(
            (
                (labels["quantity"], _display(record.get("quantity"), labels, quantity=True)),
                (labels["series"], _display(record.get("series"), labels)),
                (labels["serial_from"], _display(record.get("serial_from"), labels)),
                (labels["serial_to"], _display(record.get("serial_to"), labels)),
            )
        )
    return rows


def _receipt_rows(
    paper: dict[str, Any], labels: dict[str, str], locale: ReportLocale
) -> list[list[str]]:
    reentry = paper.get("reentry")
    if not isinstance(reentry, dict):
        return []
    record = _canonical_record(paper)
    rows = [
        [labels["paper_reference"], str(paper["paper_reference"])],
        [labels["workflow"], labels[paper["workflow"]]],
        [labels["request_id"], str(reentry["request_id"])],
        [labels["receipt_actor_id"], str(reentry["actor_id"])],
        [labels["reentry_server_entered_at"], _time(reentry.get("entered_at"), labels)],
        [labels["receipt_record_id"], _display(record.get("id"), labels)],
        [labels["receipt_revision"], _display(record.get("revision"), labels)],
        [labels["receipt_status"], labels.get(str(record.get("status") or ""), labels["none"])],
    ]
    if paper["workflow"] == "allocation":
        counter = record.get("counter")
        if isinstance(counter, dict):
            counter_value = " · ".join(
                str(counter[key]) for key in ("code", "name", "id") if counter.get(key)
            )
        else:
            counter_value = _display(record.get("counter_id"), labels)
        rows.extend(
            (
                [labels["counter"], _display(counter_value, labels)],
                [labels["event_at"], _time(record.get("event_at"), labels)],
            )
        )
    elif paper["workflow"] == "turnout":
        rows.append([labels["period_index"], _display(record.get("period_index"), labels)])
        for key in ("start_at", "end_at", "event_at"):
            if key in record:
                rows.append([labels.get(key, labels["event_at"]), _time(record[key], labels)])
    elif paper["workflow"] == "count":
        for key in ("scope_id", "round_number", "round_id", "event_at", "completed_at"):
            if key in record:
                rows.append(
                    [
                        labels.get(key, labels["event_at"]),
                        _time(record[key], labels)
                        if key.endswith("_at")
                        else _display(record[key], labels),
                    ]
                )
    rows.extend([name, value] for name, value in _receipt_quantities(paper, labels, locale))
    return rows


def _outage_rows(record: dict[str, Any], labels: dict[str, str]) -> list[list[str]]:
    return [
        [labels["outage_id"], str(record["id"])],
        [labels["station_id"], str(record["station_id"])],
        [labels["reference"], record["reference"]],
        [labels["kind"], labels[record["kind"]]],
        [labels["started_at"], _time(record["started_at"], labels)],
        [labels["ended_at"], _time(record["ended_at"], labels)],
        [labels["revision"], str(record["revision"])],
        [labels["actor_id"], str(record["actor_id"])],
        [labels["entered_at"], _time(record["entered_at"], labels)],
        [labels["notes"], record["notes"] or labels["none"]],
        [labels["reason"], record["amendment_reason"] or labels["none"]],
    ]


def _outage_history_rows(history: list[dict[str, Any]], labels: dict[str, str]) -> list[list[str]]:
    return [
        [
            labels["revision"],
            labels["reference"],
            labels["kind"],
            labels["started_at"],
            labels["ended_at"],
            labels["actor_id"],
            labels["entered_at"],
            labels["reason"],
        ],
        *[
            [
                str(row["revision"]),
                row["reference"],
                labels[row["kind"]],
                _time(row["started_at"], labels),
                _time(row["ended_at"], labels),
                str(row["actor_id"]),
                _time(row["entered_at"], labels),
                row.get("amendment_reason") or labels["none"],
            ]
            for row in history
        ],
    ]


def _paper_rows(papers: list[dict[str, Any]], labels: dict[str, str]) -> list[list[str]]:
    return [
        [
            labels["paper_id"],
            labels["paper_reference"],
            labels["workflow"],
            labels["action"],
            labels["target"],
            labels["original_event_at"],
            labels["paper_server_entered_at"],
            labels["status"],
            labels["revision"],
            labels["receipt"],
        ],
        *[
            [
                str(paper["id"]),
                paper["paper_reference"],
                labels[paper["workflow"]],
                labels[paper["action"]],
                _target_text(paper["target"], labels),
                _time(paper["original_event_at"], labels),
                _time(paper["entered_at"], labels),
                labels[paper["status"]],
                str(paper["revision"]),
                str((paper.get("reentry") or {}).get("request_id", labels["none"])),
            ]
            for paper in papers
        ],
    ]


def _paper_history_rows(papers: list[dict[str, Any]], labels: dict[str, str]) -> list[list[str]]:
    rows = [
        [
            labels["paper_reference"],
            labels["revision"],
            labels["workflow"],
            labels["action"],
            labels["target"],
            labels["original_event_at"],
            labels["actor_id"],
            labels["entered_at"],
            labels["reason"],
        ]
    ]
    for paper in papers:
        for revision in paper.get("history", []):
            rows.append(
                [
                    paper["paper_reference"],
                    str(revision["revision"]),
                    labels[paper["workflow"]],
                    labels[revision.get("action", paper["action"])],
                    _target_text(revision.get("target", paper["target"]), labels),
                    _time(revision["original_event_at"], labels),
                    str(revision["actor_id"]),
                    _time(revision["entered_at"], labels),
                    revision.get("amendment_reason") or labels["none"],
                ]
            )
    return rows


def _reconciliation_rows(
    record: dict[str, Any], labels: dict[str, str]
) -> tuple[list[list[str]], list[list[str]], list[list[str]]]:
    current = record.get("reconciliation")
    current_rows = [[labels["field"], labels["value"]]]
    if current is None:
        current_rows.append([labels["reconciled"], labels["no"]])
    else:
        current_rows.extend(
            [
                [labels["revision"], str(current["revision"])],
                [
                    labels["reconciled"],
                    labels["yes"] if current["valid"] else labels["needs_review"],
                ],
                [labels["is_current"], labels["yes"] if current["is_current"] else labels["no"]],
                [labels["reviewer_id"], str(current["actor_id"])],
                [labels["accepted_at"], _time(current["accepted_at"], labels)],
                [labels["reason"], current["reason"]],
                [labels["basis_digest"], current["basis_digest"]],
                [labels["outage_revision_id"], str(current["basis"]["outage_revision_id"])],
                [labels["outage_revision"], str(current["basis"]["outage_revision"])],
            ]
        )
    decisions = [
        [
            labels["revision"],
            labels["is_current"],
            labels["reconciled"],
            labels["reviewer_id"],
            labels["accepted_at"],
            labels["reason"],
            labels["basis_digest"],
        ]
    ]
    membership = [
        [
            labels["paper_id"],
            labels["paper_reference"],
            labels["paper_revision"],
            labels["request_id"],
            labels["receipt_actor_id"],
            labels["reentry_server_entered_at"],
        ]
    ]
    by_paper = {paper["id"]: paper for paper in record["paper_records"]}
    for decision in record.get("reconciliation_history", []):
        decisions.append(
            [
                str(decision["revision"]),
                labels["yes"] if decision["is_current"] else labels["no"],
                labels["yes"] if decision["valid"] else labels["needs_review"],
                str(decision["actor_id"]),
                _time(decision["accepted_at"], labels),
                decision["reason"],
                decision["basis_digest"],
            ]
        )
        basis = decision["basis"]
        revision_by_id = {row["paper_id"]: row["revision"] for row in basis["paper_revisions"]}
        for entry in basis["paper_entries"]:
            paper = by_paper.get(entry["paper_id"], {})
            membership.append(
                [
                    str(entry["paper_id"]),
                    paper.get("paper_reference", labels["none"]),
                    str(revision_by_id.get(entry["paper_id"], labels["none"])),
                    str(entry["request_id"] or labels["none"]),
                    str(entry["actor_id"] or labels["none"]),
                    _time(entry["entered_at"], labels),
                ]
            )
    if len(decisions) == 1:
        decisions.append([labels["none"]] * 7)
    if len(membership) == 1:
        membership.append([labels["none"]] * 6)
    return current_rows, decisions, membership


def _projection(
    snapshot: dict[str, Any],
    scope: dict[str, Any],
    generated_at: datetime,
    locale: ReportLocale,
) -> dict[str, Any]:
    labels = OUTAGE_REPORT_LABELS[locale]
    record, history = snapshot["record"], snapshot["history"]
    station = scope["station"]
    metadata = [
        [labels["election"], scope["election"]["name"]],
        [labels["election_status"], labels[scope["election"]["status"]]],
        [
            labels["constituency"],
            scope["constituency"]["code"] + " · " + scope["constituency"]["name"],
        ],
        [labels["station"], station["code"] + " · " + station["name"]],
        [labels["outage_id"], str(record["id"])],
        [labels["reference"], record["reference"]],
        [labels["revision"], str(record["revision"])],
        [labels["reconciled"], labels["yes"] if record["reconciled"] else labels["needs_review"]],
        [labels["report_basis"], labels["report_scope"]],
        [labels["connectivity_notice"], labels["connectivity_note"]],
        [labels["generated_at"], _time(generated_at, labels)],
        [labels["time_basis"], "Asia/Hong_Kong (UTC+08:00)"],
    ]
    papers = record["paper_records"]
    current_reconciliation, decisions, membership = _reconciliation_rows(record, labels)
    sections: list[dict[str, Any]] = [
        {
            "title": labels["outage"],
            "rows": _outage_rows(record, labels),
            "empty_message": "",
            "split_in_row": False,
        },
        {
            "title": labels["outage_history"],
            "rows": _outage_history_rows(history, labels),
            "empty_message": labels["empty_history"] if not history else "",
            "split_in_row": False,
        },
        {
            "title": labels["paper_records"],
            "rows": _paper_rows(papers, labels),
            "empty_message": labels["empty_papers"] if not papers else "",
            "split_in_row": False,
        },
        {
            "title": labels["paper_history"],
            "rows": _paper_history_rows(papers, labels),
            "empty_message": (
                labels["empty_history"] if not any(paper.get("history") for paper in papers) else ""
            ),
            "split_in_row": False,
        },
        {
            "title": labels["receipt_details"],
            "rows": [
                [labels["field"], labels["value"]],
                *[row for paper in papers for row in _receipt_rows(paper, labels, locale)],
            ],
            "empty_message": (
                labels["empty_papers"] if not any(paper.get("reentry") for paper in papers) else ""
            ),
            "split_in_row": False,
        },
        {
            "title": labels["reconciliation"],
            "rows": current_reconciliation,
            "empty_message": "",
            "split_in_row": False,
        },
        {
            "title": labels["reconciliation_history"],
            "rows": decisions,
            "empty_message": "",
            "split_in_row": False,
        },
        {
            "title": labels["membership"],
            "rows": membership,
            "empty_message": "",
            "split_in_row": False,
        },
    ]
    preview = [labels["title"]]
    preview.extend(value for row in metadata for value in row)
    for section in sections:
        preview.append(section["title"])
        preview.extend(value for row in section["rows"] for value in row)
        if section["empty_message"]:
            preview.append(section["empty_message"])
    return {
        "basis_digest": outage_snapshot_digest(snapshot),
        "title": labels["title"],
        "locale": locale,
        "station_id": record["station_id"],
        "outage_id": record["id"],
        "revision": record["revision"],
        "revision_state": "current",
        "generated_at": _time(generated_at, labels),
        "generation_timezone": "Asia/Hong_Kong",
        "time_basis": "Asia/Hong_Kong (UTC+08:00)",
        "metadata": metadata,
        "sections": sections,
        "preview_lines": preview,
    }


def _history_tables(projection: dict[str, Any]) -> list[HistoryTable]:
    tables = []
    for section in projection["sections"]:
        rows: list[list[str]] = section["rows"]
        localized = OUTAGE_REPORT_LABELS[projection["locale"]]
        if section["title"] in (localized["paper_records"], localized["paper_history"]):
            # Paper references and receipt UUIDs need room to remain readable;
            # the compact CSV matrix is a poor fit for ten PDF columns.
            for row in rows[1:]:
                reference_index = 1 if section["title"] == localized["paper_records"] else 0
                tables.append(
                    HistoryTable(
                        section["title"] + " · " + row[reference_index],
                        [
                            [localized["field"], localized["value"]],
                            *[
                                [heading, value]
                                for heading, value in zip(rows[0], row, strict=True)
                            ],
                        ],
                        (0.28, 0.72),
                        split_in_row=False,
                    )
                )
            if len(rows) == 1:
                tables.append(
                    HistoryTable(
                        section["title"],
                        [
                            [localized["field"], localized["value"]],
                            [localized["paper_reference"], localized["none"]],
                        ],
                        (0.28, 0.72),
                        section["empty_message"],
                    )
                )
            continue
        if section["title"] == OUTAGE_REPORT_LABELS[projection["locale"]]["outage"]:
            localized = OUTAGE_REPORT_LABELS[projection["locale"]]
            rows = [[localized["field"], localized["value"]], *rows]
            widths: tuple[float, ...] = (0.28, 0.72)
        else:
            widths = tuple([1 / len(rows[0])] * len(rows[0])) if rows and rows[0] else (0.5, 0.5)
        tables.append(
            HistoryTable(
                section["title"],
                rows,
                widths,
                section["empty_message"],
                split_in_row=section["split_in_row"],
            )
        )
    return tables


def _csv_report(projection: dict[str, Any]) -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([projection["title"]])
    writer.writerows(projection["metadata"])
    for section in projection["sections"]:
        writer.writerow([])
        writer.writerow([section["title"]])
        writer.writerows(section["rows"])
        if section["empty_message"]:
            writer.writerow([section["empty_message"]])
    return output.getvalue().encode("utf-8-sig")


def _pdf_report(projection: dict[str, Any]) -> bytes:
    labels = OUTAGE_REPORT_LABELS[projection["locale"]]
    footer = (
        labels["station_id"]
        + " "
        + str(projection["station_id"])
        + " · "
        + labels["outage_id"]
        + " "
        + str(projection["outage_id"])
        + " · "
        + labels["revision"]
        + " "
        + str(projection["revision"])
    )
    return history_pdf(
        projection["title"],
        projection["metadata"],
        _history_tables(projection),
        footer,
        labels["page"],
    )


def outage_report_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/outages/{outage_id}",
        tags=["Application outage statements"],
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    def projection(
        station_id: int,
        outage_id: int,
        db: Session,
        actor: Account,
        locale: ReportLocale,
        expected_basis: str | None,
    ) -> dict[str, Any]:
        snapshot = read_outage_snapshot(db, actor, station_id, outage_id)
        if expected_basis is not None and expected_basis != outage_snapshot_digest(snapshot):
            raise HTTPException(409, detail={"code": "outage_revision_conflict"})
        scope = stock_scope(db, actor, station_id)
        return _projection(snapshot, scope, timestamp(), locale)

    @router.get("/statement")
    def statement(
        station_id: int,
        outage_id: int,
        db: Database,
        actor: Ready,
        locale: ReportLocale = "tc",
        expected_basis: Annotated[
            str | None, Query(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")
        ] = None,
    ) -> dict[str, Any]:
        return projection(station_id, outage_id, db, actor, locale, expected_basis)

    @router.get("/statement.csv")
    def statement_csv(
        station_id: int,
        outage_id: int,
        db: Database,
        actor: Ready,
        locale: ReportLocale = "tc",
        expected_basis: Annotated[
            str | None, Query(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")
        ] = None,
    ) -> Response:
        report = projection(station_id, outage_id, db, actor, locale, expected_basis)
        filename = f"outage-{outage_id}-r{report['revision']}-{locale}.csv"
        return Response(
            _csv_report(report),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/statement.pdf")
    def statement_pdf(
        station_id: int,
        outage_id: int,
        db: Database,
        actor: Ready,
        locale: ReportLocale = "tc",
        expected_basis: Annotated[
            str | None, Query(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")
        ] = None,
    ) -> Response:
        report = projection(station_id, outage_id, db, actor, locale, expected_basis)
        filename = f"outage-{outage_id}-r{report['revision']}-{locale}.pdf"
        return Response(
            _pdf_report(report),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
