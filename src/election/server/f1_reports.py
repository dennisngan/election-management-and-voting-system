"""Self-contained F1 draft statements with exact observations and frozen provenance."""

import csv
from collections.abc import Callable
from datetime import UTC, datetime
from io import StringIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.counting_round_models import CountRoundRevision
from election.server.counting_rounds import round_at, round_context, round_view
from election.server.f1_labels import LABELS
from election.server.history_pdf import HistoryTable, history_pdf
from election.server.models import Account
from election.server.stock_reports import ReportLocale
from election.server.turnout_reports import hong_kong_time

_F1_OBSERVATION_NOTES: dict[ReportLocale, str] = {
    "tc": "本節列出點票記錄中的 F1 觀察部分；輪次狀態另行列出。",
    "sc": "本节列出点票记录中的 F1 观察部分；轮次状态另行列出。",
    "en": "This section shows the F1 observation portion of the count record.",
}
_ROUND_STATUS_LABELS: dict[ReportLocale, dict[str, str]] = {
    "tc": {"submitted": "已提交", "approved": "已核准"},
    "sc": {"submitted": "已提交", "approved": "已批准"},
    "en": {"submitted": "Submitted", "approved": "Approved"},
}


def _value(key: str, value: Any, labels: dict[str, str]) -> str:
    if value is None or value == "":
        return labels["not_recorded"]
    if isinstance(value, bool):
        return labels["yes" if value else "no"]
    if key.endswith("_at"):
        return hong_kong_time(value)
    if key in ("status", "p18_status", "translation_provenance"):
        return labels[str(value)]
    return str(value)


def _pairs(data: dict[str, Any], keys: tuple[str, ...], labels: dict[str, str]) -> list[list[str]]:
    return [[labels[key], _value(key, data.get(key), labels)] for key in keys]


def _table(title: str, rows: list[list[str]], labels: dict[str, str]) -> HistoryTable:
    return HistoryTable(title, [[labels["field"], labels["value"]], *rows], (0.40, 0.60))


def _station(station: dict[str, Any]) -> str:
    return f"#{station['id']} · {station['code']} · {station['name']}"


def _metadata(report: dict[str, Any]) -> list[list[str]]:
    record, labels, context = report["record"], report["labels"], report["context"]
    return [
        [labels["election"], record["context"]["election"]["name"]],
        [labels["election_status"], labels[context["election"]["status"]]],
        [labels["constituency"], _station(record["context"]["constituency"])],
        [labels["counting_station"], _station(record["context"]["station"])],
        [labels["scope_id"], str(record["scope_id"])],
        [labels["reference"], record["scope_basis"]["reference"]],
        *_pairs(
            {**record, "round_id": record["id"]},
            (
                "scope_revision",
                "round_id",
                "round_number",
                "revision_id",
                "revision",
                "status",
                "is_current",
                "source_current",
                "f1_complete",
                "event_at",
                "entered_at",
                "actor_id",
                "notes",
                "amendment_reason",
            ),
            labels,
        ),
        [labels["generated_at"], hong_kong_time(report["generated_at"])],
        [labels["time_basis"], "Asia/Hong_Kong (UTC+08:00)"],
    ]


def _tables(report: dict[str, Any]) -> list[HistoryTable]:
    labels, record = report["labels"], report["record"]
    tables = [
        _table(
            labels["f1_summary"],
            [
                [labels["status"], labels[str(record["status"])]],
                [labels["report_scope"], _F1_OBSERVATION_NOTES[report["locale"]]],
                [labels["coverage"], labels["mixed_note"]],
                *_pairs(
                    record,
                    (
                        "initial_valid_quantity",
                        "clearly_invalid_quantity",
                        "questionable_quantity",
                        "actual_counted_quantity",
                        "initial_accounted_quantity",
                        "initial_arithmetic_valid",
                    ),
                    labels,
                ),
                *_pairs(
                    record["scope_basis"],
                    (
                        "estimated_box_from_stock_quantity",
                        "estimated_box_from_turnout_quantity",
                    ),
                    labels,
                ),
            ],
            labels,
        )
    ]
    f1_blockers = record.get("f1_blockers", record["blockers"])
    blockers = [
        [
            labels[row["code"]],
            "; ".join(
                labels[key] + " " + str(row[key])
                for key in ("candidate_id", "reason_id")
                if key in row
            )
            or labels["none"],
        ]
        for row in f1_blockers
    ]
    tables.append(
        _table(
            labels["blockers"],
            blockers
            or [
                [labels["blocker_none"], labels["none"]],
            ],
            labels,
        )
    )
    for candidate in record["candidate_votes"]:
        tables.append(
            _table(
                labels["candidate_tally"] + f" · {candidate['ballot_number']}",
                _pairs(
                    {**candidate, "candidate_name": candidate["name"]},
                    (
                        "candidate_id",
                        "candidate_revision",
                        "ballot_number",
                        "candidate_name",
                        "quantity",
                    ),
                    labels,
                ),
                labels,
            )
        )
    for reason in record["invalid_papers"]:
        displayed = {
            **reason,
            "reason_code": reason["code"],
            "reason_label": reason["label_" + report["locale"]],
        }
        tables.append(
            _table(
                labels["invalid_papers"] + " · " + reason["code"],
                _pairs(
                    displayed,
                    (
                        "reason_id",
                        "reason_revision",
                        "reason_code",
                        "reason_label",
                        "quantity",
                        "explanation",
                        "explanation_required",
                        "verified_source",
                        "source_english",
                        "source_letter",
                        "reference_page",
                        "reference_printed_page",
                        "translation_provenance",
                    ),
                    labels,
                ),
                labels,
            )
        )
    for box in record["scope_basis"]["box_basis"]:
        tables.append(
            _table(
                labels["box_basis"] + " · " + box["box_reference"],
                [
                    *_pairs(
                        {**box, "box_id": box["id"]},
                        (
                            "box_id",
                            "box_reference",
                            "seal_reference",
                            "revision",
                        ),
                        labels,
                    ),
                    [labels["origin"], _station(box["origin"])],
                    [labels["destination"], _station(box["destination"])],
                    [labels["receipt"], hong_kong_time(box["receipt"]["event_at"])],
                ],
                labels,
            )
        )
    for source in record["scope_basis"]["accounting_basis"]:
        fields = {
            "p18_id": source["id"],
            "p18_revision": source["revision"],
            "p18_status": source["status"],
            "frozen_p18_approval_valid": source["approval_valid"],
            **source["summary"],
        }
        tables.append(
            _table(
                labels["accounting_basis"] + " · " + str(source["station_id"]),
                [
                    [labels["report_scope"], labels["accounting_note"]],
                    *_pairs(
                        fields,
                        (
                            "p18_id",
                            "p18_revision",
                            "p18_status",
                            "frozen_p18_approval_valid",
                            "received_quantity",
                            "replacement_unissued_quantity",
                            "estimated_box_from_stock_quantity",
                            "estimated_box_from_turnout_quantity",
                            "observed_counted_quantity",
                        ),
                        labels,
                    ),
                ],
                labels,
            )
        )
    for coverage in record["scope_basis"]["coverage"]:
        tables.append(
            _table(
                labels["coverage"] + " · " + _station(coverage["station"]),
                [
                    [labels["scope_box_ids"], ", ".join(map(str, coverage["scope_box_ids"]))],
                    [labels["source_box_ids"], ", ".join(map(str, coverage["source_box_ids"]))],
                    [
                        labels["all_source_boxes_in_scope"],
                        labels["yes" if coverage["all_source_boxes_in_scope"] else "no"],
                    ],
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
    return tables


def _rows(report: dict[str, Any]) -> list[list[str]]:
    rows = [[report["title"]], *_metadata(report)]
    for section in _tables(report):
        rows += [[], [section.title], *section.rows]
    return rows


def f1_reports_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Any],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/counting-scopes/{scope_id}"
        "/rounds/{round_id}/revisions/{revision}",
        tags=["F1 statements"],
    )
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    def projection(
        station_id: int,
        scope_id: int,
        round_id: int,
        revision: int,
        locale: ReportLocale,
        db: Session,
        actor: Account,
    ) -> dict[str, Any]:
        options = round_context(db, actor, station_id, scope_id)
        round = round_at(db, scope_id, round_id)
        row = db.scalar(
            select(CountRoundRevision)
            .where(
                CountRoundRevision.round_id == round_id,
                CountRoundRevision.revision == revision,
            )
            .with_for_update()
        )
        if row is None:
            raise HTTPException(404, detail={"code": "count_round_not_found"})
        return {
            "station_id": station_id,
            "scope_id": scope_id,
            "round_id": round_id,
            "revision": revision,
            "locale": locale,
            "context": options["context"],
            "record": round_view(db, round, row, options),
            "labels": {**LABELS[locale], **_ROUND_STATUS_LABELS[locale]},
            "title": LABELS[locale]["title"],
            "generated_at": timestamp().replace(tzinfo=UTC),
            "generation_timezone": "Asia/Hong_Kong",
        }

    @router.get("/statement")
    def statement(
        station_id: int,
        scope_id: int,
        round_id: int,
        revision: Annotated[int, Path(ge=1)],
        db: Database,
        actor: Actor,
        locale: ReportLocale = "tc",
    ) -> dict[str, Any]:
        report = projection(station_id, scope_id, round_id, revision, locale, db, actor)
        report["metadata"] = _metadata(report)
        report["tables"] = [
            {"title": section.title, "rows": section.rows, "column_widths": section.widths}
            for section in _tables(report)
        ]
        report["preview_lines"] = [" · ".join(row) for row in _rows(report)]
        return report

    @router.get("/statement.csv")
    def statement_csv(
        station_id: int,
        scope_id: int,
        round_id: int,
        revision: Annotated[int, Path(ge=1)],
        db: Database,
        actor: Actor,
        locale: ReportLocale = "tc",
    ) -> Response:
        report = projection(station_id, scope_id, round_id, revision, locale, db, actor)
        output = StringIO(newline="")
        csv.writer(output).writerows(_rows(report))
        filename = f"f1-round-{round_id}-revision-{revision}-{locale}.csv"
        return Response(
            output.getvalue().encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/statement.pdf")
    def statement_pdf(
        station_id: int,
        scope_id: int,
        round_id: int,
        revision: Annotated[int, Path(ge=1)],
        db: Database,
        actor: Actor,
        locale: ReportLocale = "tc",
    ) -> Response:
        report = projection(station_id, scope_id, round_id, revision, locale, db, actor)
        labels = report["labels"]
        footer = (
            report["record"]["scope_basis"]["reference"]
            + " · "
            + labels["round_number"]
            + " "
            + str(report["record"]["round_number"])
            + " · "
            + labels["revision"]
            + " "
            + str(revision)
        )
        data = history_pdf(
            report["title"], _metadata(report), _tables(report), footer, labels["page"]
        )
        filename = f"f1-round-{round_id}-revision-{revision}-{locale}.pdf"
        return Response(
            data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
