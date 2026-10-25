"""Localized constituency-result statements and matching CSV/PDF exports."""

import csv
from collections.abc import Callable, Generator
from datetime import datetime
from io import StringIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from election.server.constituency_result_labels import LABELS, ReportLocale
from election.server.constituency_results import constituency_result
from election.server.history_pdf import HistoryTable, history_pdf
from election.server.models import Account
from election.server.turnout_reports import hong_kong_time


def _value(value: Any, labels: dict[str, str]) -> str:
    if value is None:
        return labels["not_recorded"]
    if isinstance(value, bool):
        return labels["yes"] if value else labels["no"]
    if isinstance(value, list):
        return ", ".join(_value(item, labels) for item in value) if value else labels["none"]
    if isinstance(value, dict):
        return labels["not_recorded"]
    return str(value)


def _blockers(rows: list[dict[str, Any]], labels: dict[str, str]) -> str:
    rendered = []
    for row in rows:
        code = row.get("code", "")
        label = labels.get("blocker_" + code, labels.get(code, code))
        details = []
        if row.get("station_id") is not None:
            details.append(f"{labels['station_id']} {row['station_id']}")
        if row.get("reason_id") is not None:
            details.append(f"{labels['reason_id']} {row['reason_id']}")
        if details:
            label += " · " + ", ".join(details)
        rendered.append(label)
    return "; ".join(rendered) if rendered else labels["none"]


def _station_label(station: dict[str, Any] | None, labels: dict[str, str]) -> str:
    if not station:
        return labels["not_recorded"]
    return f"#{station.get('id', '?')} · {station.get('code', '')} · {station.get('name', '')}"


def _contribution_tables(
    contribution: dict[str, Any], labels: dict[str, str], title: str
) -> list[HistoryTable]:
    source = contribution.get("frozen_source_context") or {}
    detail = [
        [labels["station_id"], str(contribution["station_id"])],
        [labels["scope_id"], str(contribution["scope_id"])],
        [labels["scope_revision"], str(contribution["scope_revision"])],
        [
            labels["status"],
            labels.get(source.get("status", ""), source.get("status", labels["not_recorded"])),
        ],
        [labels["source_current"], _value(source.get("source_current"), labels)],
        [labels["count_ready"], _value(source.get("count_ready"), labels)],
        [labels["round_status"], labels["approved_selected"]],
        [labels["round_approval_valid"], labels["yes"]],
        [labels["round_source_current"], labels["yes"]],
        [labels["round_number"], str(contribution["round_number"])],
        [labels["round_id"], str(contribution["round_id"])],
        [labels["round_revision"], str(contribution["round_revision"])],
        [labels["selection_revision"], str(contribution["selection_revision"])],
        [labels["estimate_stock"], _value(source.get("estimated_box_from_stock_quantity"), labels)],
        [
            labels["estimate_turnout"],
            _value(source.get("estimated_box_from_turnout_quantity"), labels),
        ],
        [labels["blockers"], _blockers(source.get("blockers", []), labels)],
    ]
    tables = [HistoryTable(title, [[labels["field"], labels["value"]], *detail], (0.34, 0.66))]

    boxes = source.get("box_basis", [])
    box_rows = [
        [
            labels["box_id"],
            labels["box_reference"],
            labels["box_revision"],
            labels["box_origin"],
            labels["box_destination"],
            labels["box_status"],
        ]
    ]
    box_rows.extend(
        [
            str(box.get("id", "")),
            str(box.get("box_reference", "")),
            str(box.get("revision", "")),
            _station_label(box.get("origin"), labels),
            _station_label(box.get("destination"), labels),
            labels.get(box.get("status", ""), box.get("status", labels["not_recorded"])),
        ]
        for box in boxes
    )
    tables.append(
        HistoryTable(
            labels["box_ids"],
            box_rows,
            (0.09, 0.22, 0.12, 0.21, 0.21, 0.15),
            labels["none"] if not boxes else "",
            split_in_row=False,
        )
    )

    source_rows = [
        [
            labels["station_id"],
            labels["accounting_record"],
            labels["accounting_revision"],
            labels["status"],
            labels["source_current"],
            labels["approval_valid"],
            labels["estimate_stock"],
            labels["estimate_turnout"],
        ]
    ]
    accounting = source.get("accounting_basis", [])
    for item in accounting:
        record = item
        summary = record.get("summary") or {}
        source_rows.append(
            [
                _station_label(record.get("context", {}).get("station"), labels),
                _value(record.get("id"), labels),
                _value(record.get("revision"), labels),
                labels.get(record.get("status", ""), record.get("status", labels["not_recorded"])),
                _value(record.get("source_current"), labels),
                _value(record.get("approval_valid"), labels),
                _value(summary.get("estimated_box_from_stock_quantity"), labels),
                _value(summary.get("estimated_box_from_turnout_quantity"), labels),
            ]
        )
    tables.append(
        HistoryTable(
            labels["accounting_source"],
            source_rows,
            (0.20, 0.10, 0.10, 0.12, 0.12, 0.12, 0.12, 0.12),
            labels["none"] if not accounting else "",
            split_in_row=False,
        )
    )

    votes = contribution.get("final_candidate_votes", [])
    vote_rows = [[labels["candidate_id"], labels["name"], labels["quantity"]]]
    vote_rows.extend(
        [str(row.get("candidate_id", "")), row.get("name", ""), _value(row.get("quantity"), labels)]
        for row in votes
    )
    tables.append(
        HistoryTable(
            labels["candidate_votes"],
            vote_rows,
            (0.22, 0.52, 0.26),
            labels["none"] if not votes else "",
            split_in_row=False,
        )
    )
    return tables


def _tables(result: dict[str, Any], labels: dict[str, str]) -> list[HistoryTable]:
    context = result["context"]
    summary = [
        [labels["election"], context["election"]["name"]],
        [
            labels["election_status"],
            labels.get(context["election"]["status"], context["election"]["status"]),
        ],
        [
            labels["constituency"],
            context["constituency"]["code"] + " · " + context["constituency"]["name"],
        ],
        [labels["complete"], labels["yes"] if result["complete"] else labels["no"]],
        [labels["provisional"], labels["yes"] if result["provisional"] else labels["no"]],
        [labels["leader_candidate_ids"], _value(result["leader_candidate_ids"], labels)],
        [labels["tie_candidate_ids"], _value(result["tie_candidate_ids"], labels)],
        [labels["resolved_candidate_id"], _value(result["resolved_candidate_id"], labels)],
        [labels["basis_digest"], result["basis_digest"]],
    ]
    tables = [
        HistoryTable(labels["title"], [[labels["field"], labels["value"]], *summary], (0.30, 0.70))
    ]

    candidate_rows = [
        [labels["candidate_id"], labels["ballot_number"], labels["name"], labels["quantity"]]
    ]
    candidate_rows.extend(
        [
            str(row["candidate_id"]),
            str(row["ballot_number"]),
            row["name"],
            _value(row["quantity"], labels),
        ]
        for row in result["candidate_totals"]
    )
    tables.append(
        HistoryTable(
            labels["candidate_totals"],
            candidate_rows,
            (0.16, 0.18, 0.42, 0.24),
            labels["none"] if not result["candidate_totals"] else "",
            split_in_row=False,
        )
    )

    if not result["contributions"]:
        tables.append(HistoryTable(labels["contributions"], [], (0.5, 0.5), labels["none"]))
    for contribution in result["contributions"]:
        title = (
            labels["contributions"]
            + " · "
            + labels["scope_id"]
            + " "
            + str(contribution["scope_id"])
        )
        tables.extend(_contribution_tables(contribution, labels, title))

    pending_rows = [
        [
            labels["code"],
            labels["station_id"],
            labels["scope_id"],
            labels["box_ids"],
            labels["blockers"],
        ]
    ]
    pending_rows.extend(
        [
            labels.get(row["code"], row["code"]),
            _value(row.get("station_id"), labels),
            _value(row.get("scope_id"), labels),
            _value(row.get("box_ids", []), labels),
            _blockers(row.get("blockers", []), labels),
        ]
        for row in result["pending"]
    )
    tables.append(
        HistoryTable(
            labels["pending"],
            pending_rows,
            (0.30, 0.12, 0.12, 0.20, 0.26),
            labels["none"] if not result["pending"] else "",
            split_in_row=False,
        )
    )

    if not result["resolution_history"]:
        tables.append(HistoryTable(labels["resolution_history"], [], (0.5, 0.5), labels["none"]))
    for decision in result["resolution_history"]:
        basis = decision["basis"]
        candidate_names = {
            item["candidate_id"]: item["name"] for item in basis.get("candidate_totals", [])
        }
        rows = [
            [labels["resolution_revision"], str(decision["revision"])],
            [
                labels["candidate"],
                candidate_names.get(decision["candidate_id"], str(decision["candidate_id"])),
            ],
            [labels["reason"], decision["reason"]],
            [labels["actor_id"], str(decision["actor_id"])],
            [labels["accepted_at"], hong_kong_time(decision["accepted_at"])],
            [labels["basis_digest"], decision["basis_digest"]],
            [labels["current"], _value(decision["is_current"], labels)],
            [labels["valid"], _value(decision["valid"], labels)],
        ]
        tables.append(
            HistoryTable(
                labels["resolution_history"],
                [[labels["field"], labels["value"]], *rows],
                (0.34, 0.66),
            )
        )
        for contribution in basis.get("contributions", []):
            title = (
                labels["resolution_basis"]
                + " · "
                + labels["scope_id"]
                + " "
                + str(contribution["scope_id"])
            )
            tables.extend(_contribution_tables(contribution, labels, title))
        snapshot_rows = [[labels["candidate_id"], labels["name"], labels["quantity"]]]
        snapshot_rows.extend(
            [
                str(row["candidate_id"]),
                candidate_names.get(row["candidate_id"], ""),
                _value(row["quantity"], labels),
            ]
            for row in basis.get("candidate_totals", [])
        )
        tables.append(
            HistoryTable(
                labels["resolution_basis"],
                snapshot_rows,
                (0.22, 0.52, 0.26),
                labels["none"] if len(snapshot_rows) == 1 else "",
                split_in_row=False,
            )
        )
    return tables


def _csv_rows(projection: dict[str, Any]) -> list[list[str]]:
    rows = [
        [projection["title"]],
        [projection["labels"]["generated_at"], hong_kong_time(projection["generated_at"])],
        [projection["labels"]["time_basis"], projection["labels"]["time_hkt"]],
    ]
    for table in projection["tables"]:
        rows.extend([[], [table.title], *table.rows])
    return rows


def _csv_bytes(projection: dict[str, Any]) -> bytes:
    output = StringIO(newline="")
    csv.writer(output).writerows(_csv_rows(projection))
    return output.getvalue().encode("utf-8-sig")


def _pdf_bytes(projection: dict[str, Any]) -> bytes:
    labels = projection["labels"]
    context = projection["result"]["context"]
    metadata = [
        [labels["election"], context["election"]["name"]],
        [
            labels["constituency"],
            context["constituency"]["code"] + " · " + context["constituency"]["name"],
        ],
        [labels["generated_at"], hong_kong_time(projection["generated_at"])],
        [labels["time_basis"], labels["time_hkt"]],
    ]
    footer = context["constituency"]["code"] + " · " + projection["result"]["basis_digest"]
    return history_pdf(projection["title"], metadata, projection["tables"], footer, labels["page"])


def constituency_reports_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/constituencies", tags=["Constituency result statements"]
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    def projection(
        db: Session, actor: Account, constituency_id: int, locale: ReportLocale
    ) -> dict[str, Any]:
        result = constituency_result(db, actor, constituency_id)
        labels = LABELS[locale]
        generated = timestamp()
        tables = _tables(result, labels)
        return {
            "context": result["context"],
            "result": result,
            "locale": locale,
            "generated_at": generated,
            "title": labels["title"],
            "labels": labels,
            "tables": [
                {"title": table.title, "rows": table.rows, "widths": table.widths}
                for table in tables
            ],
            "rows": _csv_rows(
                {
                    "title": labels["title"],
                    "labels": labels,
                    "generated_at": generated,
                    "tables": tables,
                }
            ),
        }

    @router.get("/{constituency_id}/results/statement")
    def statement(
        constituency_id: int,
        db: Database,
        actor: Ready,
        locale: ReportLocale = "tc",
    ) -> dict[str, Any]:
        return projection(db, actor, constituency_id, locale)

    @router.get("/{constituency_id}/results/statement.csv")
    def statement_csv(
        constituency_id: int,
        db: Database,
        actor: Ready,
        locale: ReportLocale = "tc",
    ) -> Response:
        report = projection(db, actor, constituency_id, locale)
        return Response(
            _csv_bytes({**report, "tables": [HistoryTable(**row) for row in report["tables"]]}),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="constituency-{constituency_id}-results.csv"'
                )
            },
        )

    @router.get("/{constituency_id}/results/statement.pdf")
    def statement_pdf(
        constituency_id: int,
        db: Database,
        actor: Ready,
        locale: ReportLocale = "tc",
    ) -> Response:
        report = projection(db, actor, constituency_id, locale)
        tables = [HistoryTable(**row) for row in report["tables"]]
        content = _pdf_bytes({**report, "tables": tables})
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="constituency-{constituency_id}-results.pdf"'
                )
            },
        )

    return router
