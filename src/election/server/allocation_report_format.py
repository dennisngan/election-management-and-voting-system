"""P(14) exports preserve saved allocation provenance and stock scope."""

import csv
from io import StringIO
from typing import Any

from election.server.history_pdf import HistoryTable, history_pdf
from election.server.stock_reports import hong_kong_time


def _counter_name(item: dict[str, Any]) -> str:
    return f"{item['counter']['code']} · {item['counter']['name']}"


def _metadata_rows(projection: dict[str, Any]) -> list[list[str]]:
    labels, scope = projection["labels"], projection["scope"]
    selected = projection["report_scope"] == "allocation_revision"
    rows = [
        [labels["election"], scope["election"]["name"]],
        [labels["election_status"], labels[scope["election"]["status"]]],
        [
            labels["constituency"],
            scope["constituency"]["code"] + " · " + scope["constituency"]["name"],
        ],
        [labels["station"], scope["station"]["code"] + " · " + scope["station"]["name"]],
        [labels["report_scope"], labels[projection["report_scope"]]],
        [labels["revision_state"], labels[projection["revision_state"]]],
        [labels["generated_at"], hong_kong_time(projection["generated_at"])],
        [labels["time_basis"], "Asia/Hong_Kong (UTC+08:00)"],
        [labels["record_value"], labels["revision_legend" if selected else "station_legend"]],
    ]
    if selected:
        item = projection["items"][0]
        rows.extend(
            [
                [labels["allocation_id"], str(item["id"])],
                [labels["revision"], str(item["revision"])],
                [labels["counter"], _counter_name(item)],
            ]
        )
    return rows


def _allocation_table_rows(projection: dict[str, Any]) -> list[list[str]]:
    labels = projection["labels"]
    rows = [
        [
            labels[key]
            for key in (
                "allocation_id",
                "revision",
                "counter",
                "series",
                "serial_from",
                "serial_to",
                "quantity",
            )
        ],
    ]
    for item in projection["items"]:
        rows.append(
            [
                str(item["id"]),
                str(item["revision"]),
                _counter_name(item),
                item["series"],
                item["serial_from"],
                item["serial_to"],
                str(item["quantity"]),
            ]
        )
    return rows


def _allocation_rows(projection: dict[str, Any]) -> list[list[str]]:
    labels = projection["labels"]
    rows = [[labels["allocations"]], *_allocation_table_rows(projection)]
    if not projection["items"]:
        rows.append([labels["empty_allocations"]])
    for item in projection["items"]:
        rows.extend(
            [
                [],
                [labels["allocation_id"], str(item["id"])],
                [labels["revision"], str(item["revision"])],
                [labels["counter"], _counter_name(item)],
                [labels["status"], labels[item["status"]]],
                [labels["event_at"], hong_kong_time(item["event_at"])],
                [labels["entered_at"], hong_kong_time(item["entered_at"])],
                [labels["actor_id"], str(item["actor_id"])],
                [labels["reason"], item["reason"] or labels["none"]],
                [labels["receipt_basis"]],
                [labels["receipt_id"], labels["revision"], labels["range_line"]],
            ]
        )
        for basis in item["receipt_basis"]:
            rows.append(
                [str(basis["receipt_id"]), str(basis["revision"]), str(basis["range_line"] + 1)]
            )
    return rows


def _availability_rows(projection: dict[str, Any]) -> list[list[str]]:
    labels = projection["labels"]
    rows = [
        [labels["availability"]],
        [
            labels[key]
            for key in (
                "series",
                "ordinary_received_quantity",
                "allocated_quantity",
                "available_quantity",
                "replacement_quantity",
                "tendered_quantity",
            )
        ],
    ]
    for balance in projection["availability"]:
        rows.append(
            [
                balance["series"],
                str(balance["ordinary_received_quantity"]),
                str(balance["allocated_quantity"]),
                str(balance["available_quantity"]),
                str(balance["replacement_quantity"]),
                str(balance["tendered_quantity"]),
            ]
        )
    if not projection["availability"]:
        rows.append([labels["empty_ranges"]])
    for balance in projection["availability"]:
        rows.extend(
            [
                [],
                [labels["series"], balance["series"]],
                [labels["available_ranges"]],
                [
                    labels["serial_from"],
                    labels["serial_to"],
                    labels["quantity"],
                    labels["receipt_id"],
                    labels["revision"],
                ],
            ]
        )
        for line in balance["ranges"]:
            rows.append(
                [
                    line["serial_from"],
                    line["serial_to"],
                    str(line["quantity"]),
                    str(line["receipt_id"]),
                    str(line["receipt_revision"]),
                ]
            )
        if not balance["ranges"]:
            rows.append([labels["empty_ranges"]])
    return rows


def _report_rows(projection: dict[str, Any]) -> list[list[str]]:
    rows = [[projection["title"]], *_metadata_rows(projection), [], *_allocation_rows(projection)]
    if projection["report_scope"] == "station_current":
        rows.extend([[], *_availability_rows(projection)])
    return rows


def csv_report(projection: dict[str, Any]) -> bytes:
    output = StringIO(newline="")
    csv.writer(output).writerows(_report_rows(projection))
    return output.getvalue().encode("utf-8-sig")


def preview_lines(projection: dict[str, Any]) -> list[str]:
    return [" · ".join(row) for row in _report_rows(projection)]


def _allocation_detail_table(item: dict[str, Any], labels: dict[str, str]) -> HistoryTable:
    identity = (
        f"{labels['details']} · {labels['allocation_id']} {item['id']}"
        f" · {labels['revision']} {item['revision']}"
    )
    rows = [
        [labels["field"] + "\n" + identity, labels["value"]],
        [labels["allocation_id"], str(item["id"])],
        [labels["revision"], str(item["revision"])],
        [labels["status"], labels[item["status"]]],
        [labels["counter"], _counter_name(item)],
        [labels["series"], item["series"]],
        [labels["serial_from"], item["serial_from"]],
        [labels["serial_to"], item["serial_to"]],
        [labels["quantity"], str(item["quantity"])],
        [labels["event_at"], hong_kong_time(item["event_at"])],
        [labels["entered_at"], hong_kong_time(item["entered_at"])],
        [labels["actor_id"], str(item["actor_id"])],
        [labels["reason"], item["reason"] or labels["none"]],
    ]
    for basis in item["receipt_basis"]:
        rows.append(
            [
                f"{labels['receipt_basis']} · {labels['receipt_id']} {basis['receipt_id']}",
                f"{labels['revision']} {basis['revision']}"
                f" · {labels['range_line']} {basis['range_line'] + 1}",
            ]
        )
    return HistoryTable("", rows, (0.30, 0.70))


def _availability_tables(projection: dict[str, Any]) -> list[HistoryTable]:
    labels = projection["labels"]
    overview = [
        [
            labels[key]
            for key in (
                "series",
                "ordinary_received_quantity",
                "allocated_quantity",
                "available_quantity",
                "replacement_quantity",
                "tendered_quantity",
            )
        ],
        *[
            [
                balance["series"],
                str(balance["ordinary_received_quantity"]),
                str(balance["allocated_quantity"]),
                str(balance["available_quantity"]),
                str(balance["replacement_quantity"]),
                str(balance["tendered_quantity"]),
            ]
            for balance in projection["availability"]
        ],
    ]
    sections = [
        HistoryTable(
            labels["availability"],
            overview,
            (0.25, 0.15, 0.15, 0.15, 0.15, 0.15),
            labels["empty_ranges"] if not projection["availability"] else "",
            split_in_row=False,
        )
    ]
    for balance in projection["availability"]:
        rows = [
            [
                labels["serial_from"],
                labels["serial_to"],
                labels["quantity"],
                labels["receipt_id"],
                labels["revision"],
            ],
            *[
                [
                    line["serial_from"],
                    line["serial_to"],
                    str(line["quantity"]),
                    str(line["receipt_id"]),
                    str(line["receipt_revision"]),
                ]
                for line in balance["ranges"]
            ],
        ]
        sections.append(
            HistoryTable(
                labels["available_ranges"] + " · " + balance["series"],
                rows,
                (0.25, 0.25, 0.20, 0.15, 0.15),
                labels["empty_ranges"] if not balance["ranges"] else "",
                split_in_row=False,
            )
        )
    return sections


def pdf_report(projection: dict[str, Any]) -> bytes:
    labels = projection["labels"]
    sections = [
        HistoryTable(
            labels["allocations"],
            _allocation_table_rows(projection),
            (0.07, 0.06, 0.21, 0.20, 0.18, 0.18, 0.10),
            labels["empty_allocations"] if not projection["items"] else "",
            split_in_row=False,
        ),
        *[_allocation_detail_table(item, labels) for item in projection["items"]],
    ]
    if projection["report_scope"] == "station_current":
        sections.extend(_availability_tables(projection))
        footer = projection["scope"]["station"]["code"] + " · " + labels["station_current"]
    else:
        footer = (
            f"{labels['allocation_id']} {projection['allocation_id']}"
            f" · {labels['revision']} {projection['revision']}"
            f" · {labels[projection['revision_state']]}"
        )
    return history_pdf(
        projection["title"], _metadata_rows(projection), sections, footer, labels["page"]
    )
