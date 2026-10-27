"""Shared localized report tables for live and approval-time physical reviews."""

from typing import Any

from election.server.history_pdf import HistoryTable
from election.server.turnout_reports import hong_kong_time


def _value(key: str, value: Any, labels: dict[str, str]) -> str:
    if value is None or value == "":
        return labels["not_recorded"]
    if isinstance(value, bool):
        return labels["yes" if value else "no"]
    if key.endswith("_at"):
        return hong_kong_time(value)
    if key in ("status", "comparison_status"):
        return labels.get(str(value), str(value))
    return str(value)


def _pairs(
    data: dict[str, Any],
    fields: tuple[tuple[str, str], ...],
    labels: dict[str, str],
) -> list[list[str]]:
    return [[labels[label], _value(key, data.get(key), labels)] for label, key in fields]


def _table(title: str, rows: list[list[str]], labels: dict[str, str]) -> HistoryTable:
    return HistoryTable(title, [[labels["field"], labels["value"]], *rows], (0.40, 0.60))


def physical_tables(
    record: dict[str, Any],
    labels: dict[str, str],
    *,
    include_empty_placeholders: bool = True,
) -> list[HistoryTable]:
    """Render live decision history and separately frozen approval context."""
    tables: list[HistoryTable] = []
    decision_fields = (
        ("decision_revision", "revision"),
        ("reviewed_count_revision", "reviewed_revision"),
        ("reviewed_count_revision_id", "reviewed_revision_id"),
        ("scope_revision", "scope_revision"),
        ("decision_actor", "actor_id"),
        ("accepted_at", "accepted_at"),
        ("acceptance_reason", "reason"),
        ("expected_quantity", "expected_quantity"),
        ("actual_quantity", "actual_quantity"),
        ("difference_quantity", "difference_quantity"),
        ("applies_to_revision", "applies_to_revision"),
        ("decision_validity", "valid"),
        ("decision_is_current", "is_current"),
        ("fingerprint", "fingerprint"),
    )
    for key, title_key in (
        ("physical_decisions", "physical_decision_history"),
        ("approved_physical_decisions", "physical_decision_approved"),
    ):
        for decision in record.get(key, []):
            source = labels.get("source_" + decision["source"], decision["source"])
            tables.append(
                _table(
                    labels[title_key] + " · " + source,
                    _pairs(decision, decision_fields, labels),
                    labels,
                )
            )

    for comparison in record.get("physical_comparisons", []):
        source = labels.get("source_" + comparison["source"], comparison["source"])
        fields = [
            ("source", "source_label"),
            ("expected_quantity", "expected_quantity"),
            ("actual_quantity", "actual_quantity"),
            ("difference_quantity", "difference_quantity"),
        ]
        if "available" in labels:
            fields.append(("available", "available"))
        fields.append(("comparison_status", "status"))
        rows = _pairs({**comparison, "source_label": source}, tuple(fields), labels)
        acceptance = comparison.get("acceptance")
        if acceptance:
            rows.extend(
                _pairs(
                    acceptance,
                    (
                        ("decision_actor", "actor_id"),
                        ("accepted_at", "accepted_at"),
                        ("acceptance_reason", "reason"),
                        ("reviewed_count_revision", "reviewed_revision"),
                    ),
                    labels,
                )
            )
        tables.append(_table(labels["physical_comparisons"] + " · " + source, rows, labels))

    for comparison in record.get("reviewed_physical_comparisons", []):
        source = labels.get("source_" + comparison["source"], comparison["source"])
        tables.append(
            _table(
                labels["physical_comparison_reviewed"] + " · " + source,
                _pairs(
                    {**comparison, "source_label": source},
                    (
                        ("source", "source_label"),
                        ("expected_quantity", "expected_quantity"),
                        ("actual_quantity", "actual_quantity"),
                        ("difference_quantity", "difference_quantity"),
                        ("comparison_status", "status"),
                    ),
                    labels,
                ),
                labels,
            )
        )

    has_decision_context = any(
        record.get(key)
        for key in (
            "physical_decisions",
            "approved_physical_decisions",
            "reviewed_physical_comparisons",
        )
    )
    if include_empty_placeholders and not has_decision_context:
        tables.append(
            _table(
                labels["physical_decision_history"],
                [[labels["form"], labels["not_recorded"]]],
                labels,
            )
        )
    if include_empty_placeholders and not record.get("physical_comparisons"):
        tables.append(
            _table(
                labels["physical_comparisons"],
                [[labels["form"], labels["not_recorded"]]],
                labels,
            )
        )
    if not tables:
        tables.append(
            _table(
                labels["physical_decision_history"],
                [[labels["form"], labels["not_recorded"]]],
                labels,
            )
        )
    return tables
