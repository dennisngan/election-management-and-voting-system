"""Selected-revision F2, F3, F4, and complete count statements."""

import csv
from collections.abc import Callable
from datetime import UTC, datetime
from io import StringIO
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.count_report_labels import LABELS
from election.server.counting_round_models import CountRoundRevision
from election.server.counting_rounds import round_at, round_context, round_view
from election.server.history_pdf import HistoryTable, history_pdf
from election.server.models import Account
from election.server.physical_decision_reports import physical_tables
from election.server.stock_reports import ReportLocale
from election.server.turnout_reports import hong_kong_time

CountReportForm = Literal["f2", "f3", "f4", "count"]


def _value(key: str, value: Any, labels: dict[str, str]) -> str:
    if value is None or value == "":
        return labels["not_recorded"]
    if isinstance(value, bool):
        return labels["yes" if value else "no"]
    if key.endswith("_at"):
        return hong_kong_time(value)
    if key in ("status", "record_state", "p18_status", "translation_provenance"):
        return labels.get(str(value), str(value))
    return str(value)


def _pairs(
    data: dict[str, Any],
    fields: tuple[tuple[str, str], ...],
    labels: dict[str, str],
) -> list[list[str]]:
    return [
        [labels[label_key], _value(data_key, data.get(data_key), labels)]
        for label_key, data_key in fields
    ]


def _table(title: str, rows: list[list[str]], labels: dict[str, str]) -> HistoryTable:
    content = [[labels["field"], labels["value"]], *rows]
    columns = max((len(row) for row in content), default=2)
    widths = (0.4, 0.6) if columns == 2 else tuple(1 / columns for _ in range(columns))
    return HistoryTable(title, content, widths)


def _station(row: dict[str, Any]) -> str:
    return f"#{row['id']} · {row['code']} · {row['name']}"


def _metadata(report: dict[str, Any]) -> list[list[str]]:
    record, labels = report["record"], report["labels"]
    context = record.get("context", report["context"])
    fields = {
        **record,
        "form": report["form"],
        "scope_reference": record["scope_basis"]["reference"],
    }
    return [
        [labels["election"], context["election"]["name"]],
        [labels["election_status"], labels[context["election"]["status"]]],
        [labels["constituency"], _station(context["constituency"])],
        [labels["counting_station"], _station(context["station"])],
        *_pairs(
            fields,
            (
                ("scope_id", "scope_id"),
                ("reference", "scope_reference"),
                ("round_id", "id"),
                ("round_number", "round_number"),
                ("revision_id", "revision_id"),
                ("revision", "revision"),
                ("record_state", "status"),
                ("form", "form"),
                ("is_current", "is_current"),
                ("source_current", "source_current"),
                ("selected", "selected"),
                ("f1_complete", "f1_complete"),
                ("f2_complete", "f2_complete"),
                ("count_inputs_complete", "count_inputs_complete"),
                ("count_complete", "count_complete"),
                ("f1_event_at", "event_at"),
                ("f1_entered_at", "entered_at"),
                ("f1_actor_id", "actor_id"),
                ("f1_notes", "notes"),
                ("f1_amendment_reason", "amendment_reason"),
                ("revision_event_at", "revision_event_at"),
                ("revision_entered_at", "revision_entered_at"),
                ("revision_actor_id", "revision_actor_id"),
                ("revision_notes", "revision_notes"),
                ("revision_amendment_reason", "revision_amendment_reason"),
                ("submitted_at", "submitted_at"),
                ("submitted_by", "submitted_by"),
                ("completed_at", "completed_at"),
                ("approved_at", "approved_at"),
                ("approved_by", "approved_by"),
                ("reviewed_revision", "reviewed_revision"),
                ("reviewed_revision_id", "reviewed_revision_id"),
                ("approval_valid", "approval_valid"),
                ("selection_valid", "selection_valid"),
            ),
            labels,
        ),
        [labels["generated_at"], hong_kong_time(report["generated_at"])],
        [labels["time_basis"], "Asia/Hong_Kong (UTC+08:00)"],
    ]


def _summary(record: dict[str, Any], labels: dict[str, str]) -> HistoryTable:
    return _table(
        labels["count_summary"],
        _pairs(
            record,
            (
                ("initial_valid_quantity", "initial_valid_quantity"),
                ("clearly_invalid_quantity", "clearly_invalid_quantity"),
                ("questionable_quantity", "questionable_quantity"),
                ("actual_counted_quantity", "actual_counted_quantity"),
                ("accepted_questionable_quantity", "accepted_questionable_quantity"),
                ("rejected_questionable_quantity", "rejected_questionable_quantity"),
                ("final_valid_quantity", "final_valid_quantity"),
                ("final_invalid_quantity", "final_invalid_quantity"),
                ("final_accounted_quantity", "final_accounted_quantity"),
                ("final_arithmetic_valid", "final_arithmetic_valid"),
            ),
            labels,
        ),
        labels,
    )


def _invalid_reason_table(
    reason: dict[str, Any], stage_label: str, labels: dict[str, str]
) -> HistoryTable:
    fields = {
        **reason,
        "display_stage": stage_label,
        "reason_code": reason["code"],
        "reason_label": reason["label_" + report_locale(labels)],
    }
    return _table(
        stage_label + " · " + reason["code"],
        _pairs(
            fields,
            (
                ("stage", "display_stage"),
                ("reason_id", "reason_id"),
                ("reason_revision", "reason_revision"),
                ("reason_code", "reason_code"),
                ("reason_label", "reason_label"),
                ("quantity", "quantity"),
                ("explanation", "explanation"),
                ("explanation_required", "explanation_required"),
                ("verified_source", "verified_source"),
                ("source_english", "source_english"),
                ("source_letter", "source_letter"),
                ("reference_page", "reference_page"),
                ("reference_printed_page", "reference_printed_page"),
                ("translation_provenance", "translation_provenance"),
            ),
            labels,
        ),
        labels,
    )


def _f2_tables(
    record: dict[str, Any],
    labels: dict[str, str],
    *,
    include_outcomes: bool = True,
) -> list[HistoryTable]:
    section_title = labels["f2_section" if include_outcomes else "f2_event_record"]
    f2 = record.get("f2")
    if f2 is None:
        return [_table(section_title, [[labels["form"], labels["not_recorded"]]], labels)]
    f2_metadata = {
        **f2,
        "accepted_questionable_quantity": record.get("accepted_questionable_quantity"),
        "rejected_questionable_quantity": record.get("rejected_questionable_quantity"),
    }
    determination_start = f2.get("determination_started_at")
    f2_metadata["determination_start_display"] = (
        labels["not_applicable"]
        if record["questionable_quantity"] == 0 and determination_start is None
        else _value("determination_started_at", determination_start, labels)
    )
    metadata_fields = [
        ("f2_event_at", "event_at"),
        ("f2_entered_at", "entered_at"),
        ("f2_actor_id", "actor_id"),
        ("determination_started_at", "determination_start_display"),
        ("f2_notes", "notes"),
        ("f2_amendment_reason", "amendment_reason"),
    ]
    if include_outcomes:
        metadata_fields.extend(
            [
                ("accepted_questionable_quantity", "accepted_questionable_quantity"),
                ("rejected_questionable_quantity", "rejected_questionable_quantity"),
            ]
        )
    tables = [
        _table(
            section_title,
            _pairs(f2_metadata, tuple(metadata_fields), labels),
            labels,
        )
    ]
    event = f2.get("determination_event")
    if event is not None:
        tables.append(
            _table(
                labels["determination_event"],
                _pairs(
                    event,
                    (
                        ("origin_revision", "origin_revision"),
                        ("f2_event_at", "event_at"),
                        ("f2_entered_at", "entered_at"),
                        ("f2_actor_id", "actor_id"),
                        ("f2_amendment_reason", "amendment_reason"),
                    ),
                    labels,
                ),
                labels,
            )
        )
    if include_outcomes:
        for candidate in f2["accepted_votes"]:
            candidate_fields = {**candidate, "candidate_name": candidate["name"]}
            tables.append(
                _table(
                    labels["f2_accepted_votes"] + " · " + str(candidate["ballot_number"]),
                    _pairs(
                        candidate_fields,
                        (
                            ("candidate_id", "candidate_id"),
                            ("candidate_revision", "candidate_revision"),
                            ("ballot_number", "ballot_number"),
                            ("candidate_name", "candidate_name"),
                            ("accepted_quantity", "quantity"),
                        ),
                        labels,
                    ),
                    labels,
                )
            )
        tables.extend(
            _invalid_reason_table(reason, labels["f2_source"], labels)
            for reason in f2["rejected_papers"]
        )
    return tables


def _f1_tables(record: dict[str, Any], labels: dict[str, str]) -> list[HistoryTable]:
    tables = []
    for candidate in record["candidate_votes"]:
        fields = {**candidate, "candidate_name": candidate["name"]}
        tables.append(
            _table(
                labels["candidate_tally"] + " · " + str(candidate["ballot_number"]),
                _pairs(
                    fields,
                    (
                        ("candidate_id", "candidate_id"),
                        ("candidate_revision", "candidate_revision"),
                        ("ballot_number", "ballot_number"),
                        ("candidate_name", "candidate_name"),
                        ("quantity", "quantity"),
                    ),
                    labels,
                ),
                labels,
            )
        )
    for reason in record["invalid_papers"]:
        tables.append(_invalid_reason_table(reason, labels["f1_source"], labels))
    return tables


def report_locale(labels: dict[str, str]) -> ReportLocale:
    """Find the report locale carried on labels for selecting frozen display wording."""
    return labels["_locale"]  # type: ignore[return-value]


def _f3_tables(record: dict[str, Any], labels: dict[str, str]) -> list[HistoryTable]:
    tables = [
        _invalid_reason_table(reason, labels["f1_source"], labels)
        for reason in record["invalid_papers"]
    ]
    f2 = record.get("f2")
    if f2 is not None:
        tables.extend(
            _invalid_reason_table(reason, labels["f2_source"], labels)
            for reason in f2["rejected_papers"]
        )
    if not tables:
        tables.append(
            _table(labels["f3_section"], [[labels["form"], labels["not_recorded"]]], labels)
        )
    return tables


def _f4_tables(record: dict[str, Any], labels: dict[str, str]) -> list[HistoryTable]:
    tables = []
    for row in record.get("final_candidate_votes", []):
        candidate_fields = {
            **row,
            "candidate_name": row["name"],
            "final_quantity": row["quantity"],
        }
        tables.append(
            _table(
                labels["f4_section"] + " · " + str(row["ballot_number"]),
                _pairs(
                    candidate_fields,
                    (
                        ("candidate_id", "candidate_id"),
                        ("candidate_revision", "candidate_revision"),
                        ("ballot_number", "ballot_number"),
                        ("candidate_name", "candidate_name"),
                        ("initial_quantity", "initial_quantity"),
                        ("accepted_quantity_per_candidate", "accepted_questionable_quantity"),
                        ("final_quantity", "final_quantity"),
                    ),
                    labels,
                ),
                labels,
            )
        )
    if not tables:
        tables.append(
            _table(labels["f4_section"], [[labels["form"], labels["not_recorded"]]], labels)
        )
    tables.append(
        _table(
            labels["f4_section"],
            _pairs(
                record,
                (
                    ("final_valid_quantity", "final_valid_quantity"),
                    ("final_invalid_quantity", "final_invalid_quantity"),
                    ("actual_counted_quantity", "actual_counted_quantity"),
                    ("final_accounted_quantity", "final_accounted_quantity"),
                    ("final_arithmetic_valid", "final_arithmetic_valid"),
                ),
                labels,
            ),
            labels,
        )
    )
    return tables


def _basis_tables(record: dict[str, Any], labels: dict[str, str]) -> list[HistoryTable]:
    basis = record["scope_basis"]
    tables = []
    for box in basis["box_basis"]:
        rows = _pairs(
            {**box, "box_id": box["id"]},
            (
                ("box_id", "box_id"),
                ("box_reference", "box_reference"),
                ("seal_reference", "seal_reference"),
                ("revision", "revision"),
            ),
            labels,
        )
        rows.extend(
            [
                [labels["origin"], _station(box["origin"])],
                [labels["destination"], _station(box["destination"])],
                [labels["receipt"], hong_kong_time(box["receipt"]["event_at"])],
            ]
        )
        tables.append(_table(labels["box_basis"] + " · " + box["box_reference"], rows, labels))
    for source in basis["accounting_basis"]:
        fields = {
            "p18_id": source["id"],
            "p18_revision": source["revision"],
            "p18_status": source["status"],
            "frozen_p18_approval_valid": source["approval_valid"],
            **source["summary"],
        }
        rows = _pairs(
            fields,
            (
                ("p18_id", "p18_id"),
                ("p18_revision", "p18_revision"),
                ("p18_status", "p18_status"),
                ("frozen_p18_approval_valid", "frozen_p18_approval_valid"),
                ("received_quantity", "received_quantity"),
                ("replacement_unissued_quantity", "replacement_unissued_quantity"),
                ("estimated_box_from_stock_quantity", "estimated_box_from_stock_quantity"),
                ("estimated_box_from_turnout_quantity", "estimated_box_from_turnout_quantity"),
                ("observed_counted_quantity", "observed_counted_quantity"),
            ),
            labels,
        )
        rows.insert(0, [labels["origin"], _station(source["context"]["station"])])
        tables.append(_table(labels["accounting_basis"], rows, labels))
    for coverage in basis["coverage"]:
        rows = [
            [labels["coverage_station"], _station(coverage["station"])],
            [labels["covered_scope_box_ids"], ", ".join(map(str, coverage["scope_box_ids"]))],
            [labels["source_box_ids"], ", ".join(map(str, coverage["source_box_ids"]))],
            [
                labels["coverage_all_boxes"],
                labels["yes" if coverage["all_source_boxes_in_scope"] else "no"],
            ],
        ]
        tables.append(_table(labels["coverage"], rows, labels))
    return tables


def _workflow_tables(record: dict[str, Any], labels: dict[str, str]) -> list[HistoryTable]:
    rows = [
        [labels["approval_valid"], _value("approval_valid", record.get("approval_valid"), labels)],
        [labels["selected"], _value("selected", record.get("selected"), labels)],
    ]
    selection = record.get("selection")
    if selection is None:
        rows.append([labels["selection"], labels["not_selected"]])
    else:
        rows.extend(
            _pairs(
                selection,
                (
                    ("selection_revision", "revision"),
                    ("selection_round_revision", "round_revision"),
                    ("selected_at", "selected_at"),
                    ("selection_actor_id", "actor_id"),
                    ("selection_valid_status", "valid"),
                ),
                labels,
            )
        )
    tables = [_table(labels["workflow_section"], rows, labels)]
    event = record.get("completion_event")
    if event is not None:
        tables.append(
            _table(
                labels["completion_event"],
                _pairs(
                    event,
                    (
                        ("origin_revision", "origin_revision"),
                        ("completed_at", "event_at"),
                        ("entered_at", "entered_at"),
                        ("actor_id", "actor_id"),
                        ("amendment_reason", "amendment_reason"),
                    ),
                    labels,
                ),
                labels,
            )
        )
    history = record.get("selection_history", [])
    for item in history:
        tables.append(
            _table(
                labels["selection_history"] + " · " + str(item["revision"]),
                _pairs(
                    item,
                    (
                        ("selection_revision", "revision"),
                        ("round_id", "round_id"),
                        ("round_number", "round_number"),
                        ("selection_round_revision", "round_revision"),
                        ("revision_id", "round_revision_id"),
                        ("scope_revision", "scope_revision"),
                        ("selected_at", "selected_at"),
                        ("selection_actor_id", "actor_id"),
                        ("selection_valid_status", "valid"),
                        ("is_current", "is_current"),
                    ),
                    labels,
                ),
                labels,
            )
        )
    if not history:
        tables.append(
            _table(
                labels["selection_history"],
                [[labels["selection"], labels["not_selected"]]],
                labels,
            )
        )
    return tables


def _comparison_tables(record: dict[str, Any], labels: dict[str, str]) -> list[HistoryTable]:
    blockers = []
    for blocker in record.get("approval_blockers", []):
        message = labels.get(blocker["code"], blocker["code"])
        if "source" in blocker:
            message += " · " + labels.get("source_" + blocker["source"], blocker["source"])
        if "difference_quantity" in blocker:
            message += " · " + _value("difference_quantity", blocker["difference_quantity"], labels)
        blockers.append(message)
    return [
        _table(
            labels["approval_blockers"],
            [[labels["approval_blockers"], "; ".join(blockers) or labels["none"]]],
            labels,
        )
    ]


def _tables(report: dict[str, Any]) -> list[HistoryTable]:
    record, labels, form = report["record"], report["labels"], report["form"]
    tables = [_summary(record, labels)]
    tables.extend(_f2_tables(record, labels, include_outcomes=form in ("f2", "count")))
    if form in ("f3", "count"):
        tables.extend(_f3_tables(record, labels))
    if form in ("f4", "count"):
        tables.extend(_f4_tables(record, labels))
    if form == "count":
        tables.extend(_f1_tables(record, labels))
    tables.extend(_workflow_tables(record, labels))
    tables.extend(physical_tables(record, labels))
    tables.extend(_comparison_tables(record, labels))
    tables.append(
        _table(
            labels["basis_section"],
            [[labels["report_scope"], labels["mixed_scope_note"]]],
            labels,
        )
    )
    tables.extend(_basis_tables(record, labels))
    return tables


def _rows(report: dict[str, Any]) -> list[list[str]]:
    rows = [[report["title"]], *_metadata(report)]
    for table in _tables(report):
        rows.extend([[], [table.title], *table.rows])
    return rows


def count_reports_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Any],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix=(
            "/api/workspace/stations/{station_id}/counting-scopes/{scope_id}"
            "/rounds/{round_id}/revisions/{revision}"
        ),
        tags=["count statements"],
    )
    Database = Annotated[Session, Depends(database)]
    Actor = Annotated[Account, Depends(ready_account)]

    def projection(
        station_id: int,
        scope_id: int,
        round_id: int,
        revision: int,
        form: CountReportForm,
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
        labels = {**LABELS[locale], "_locale": locale}
        record = round_view(db, round, row, options)
        selection = record.get("selection")
        record["selection_valid"] = selection.get("valid") if selection else None
        return {
            "station_id": station_id,
            "scope_id": scope_id,
            "round_id": round_id,
            "revision": revision,
            "form": form,
            "locale": locale,
            "context": options["context"],
            "record": record,
            "labels": labels,
            "title": labels[f"title_{form}"],
            "generated_at": timestamp().replace(tzinfo=UTC),
            "generation_timezone": "Asia/Hong_Kong",
        }

    def statement_endpoint(form: CountReportForm) -> Callable[..., dict[str, Any]]:
        def endpoint(
            station_id: int,
            scope_id: int,
            round_id: int,
            revision: Annotated[int, Path(ge=1)],
            db: Database,
            actor: Actor,
            locale: ReportLocale = "tc",
        ) -> dict[str, Any]:
            report = projection(station_id, scope_id, round_id, revision, form, locale, db, actor)
            report["metadata"] = _metadata(report)
            report["tables"] = [
                {"title": table.title, "rows": table.rows, "column_widths": table.widths}
                for table in _tables(report)
            ]
            report["preview_lines"] = [" · ".join(row) for row in _rows(report)]
            return report

        endpoint.__name__ = f"statement_{form}"
        return endpoint

    def csv_endpoint(form: CountReportForm) -> Callable[..., Response]:
        def endpoint(
            station_id: int,
            scope_id: int,
            round_id: int,
            revision: Annotated[int, Path(ge=1)],
            db: Database,
            actor: Actor,
            locale: ReportLocale = "tc",
        ) -> Response:
            report = projection(station_id, scope_id, round_id, revision, form, locale, db, actor)
            output = StringIO(newline="")
            csv.writer(output).writerows(_rows(report))
            filename = f"count-round-{round_id}-revision-{revision}-{form}-{locale}.csv"
            return Response(
                output.getvalue().encode("utf-8-sig"),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )

        endpoint.__name__ = f"statement_{form}_csv"
        return endpoint

    def pdf_endpoint(form: CountReportForm) -> Callable[..., Response]:
        def endpoint(
            station_id: int,
            scope_id: int,
            round_id: int,
            revision: Annotated[int, Path(ge=1)],
            db: Database,
            actor: Actor,
            locale: ReportLocale = "tc",
        ) -> Response:
            report = projection(station_id, scope_id, round_id, revision, form, locale, db, actor)
            record, labels = report["record"], report["labels"]
            footer = (
                record["scope_basis"]["reference"]
                + " · "
                + labels["round_number"]
                + " "
                + str(record["round_number"])
                + " · "
                + labels["revision"]
                + " "
                + str(revision)
                + " · "
                + labels["form"]
                + " "
                + form
            )
            data = history_pdf(
                report["title"], _metadata(report), _tables(report), footer, labels["page"]
            )
            filename = f"count-round-{round_id}-revision-{revision}-{form}-{locale}.pdf"
            return Response(
                data,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )

        endpoint.__name__ = f"statement_{form}_pdf"
        return endpoint

    for form in ("f2", "f3", "f4", "count"):
        router.add_api_route(f"/{form}", statement_endpoint(form), methods=["GET"])
        router.add_api_route(f"/{form}.csv", csv_endpoint(form), methods=["GET"])
        router.add_api_route(f"/{form}.pdf", pdf_endpoint(form), methods=["GET"])

    return router
