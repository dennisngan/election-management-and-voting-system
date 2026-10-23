"""Public six-box reports keep history headings with their first table row."""

from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.box_support import BoxClock, box_staff, box_stations, event_command, prepared_box
from tests.test_box_reports import (
    clear_private_active_pointer as clear_private_active_pointer,
)
from tests.test_box_reports import database_url as database_url


@pytest.mark.parametrize(
    ("locale", "heading", "reference_header", "revision_header", "first_event"),
    [
        ("tc", "票箱交收及修正歷史", "票箱識別資料", "修訂版本", "已記錄封箱準備"),
        ("sc", "票箱交收及修正历史", "票箱识别资料", "修订版本", "已记录封箱准备"),
        ("en", "Box handover and correction history", "Box reference", "Revision",
         "Preparation recorded"),
    ],
)
def test_six_box_history_heading_shares_its_page_with_header_and_first_event(
    admin: TestClient, database_url: str, tmp_path: Path, locale: str,
    heading: str, reference_header: str, revision_header: str, first_event: str,
) -> None:
    stations, clock = box_stations(admin, activate=False), BoxClock()
    election = stations["election"]
    renamed = admin.put(
        f"/api/elections/{election['id']}",
        json={"name": "票站流程驗證 Polling workflow 2025", "revision": election["revision"]},
    )
    assert renamed.status_code == 200
    constituencies = admin.get(f"/api/elections/{election['id']}/constituencies")
    assert constituencies.status_code == 200
    constituency = next(row for row in constituencies.json()["items"] if row["code"] == "N")
    changed = admin.put(
        f"/api/elections/{election['id']}/constituencies/{constituency['id']}",
        json={"code": "N", "name": "北區 North", "revision": constituency["revision"]},
    )
    assert changed.status_code == 200
    for code, name in (("N1", "北區 North 接收點票站"), ("N2", "北區 North 送箱票站")):
        station = stations[code]
        changed = admin.put(
            f"/api/elections/{election['id']}/constituencies/{constituency['id']}"
            f"/stations/{station['id']}",
            json={
                "code": code, "name": name, "revision": station["revision"],
                "counting_mode": "send" if code == "N2" else "local",
                "destination_station_id": stations["N1"]["id"] if code == "N2" else None,
            },
        )
        assert changed.status_code == 200
    activated = admin.post(
        f"/api/elections/{election['id']}/activate",
        json={"election_revision": renamed.json()["revision"], "schedule_revision": 1},
    )
    assert activated.status_code == 200
    source = f"/api/workspace/stations/{stations['N2']['id']}/boxes"
    target = f"/api/workspace/stations/{stations['N1']['id']}/boxes"
    with ExitStack() as stack:
        sender, _ = stack.enter_context(
            box_staff(admin, database_url, clock, "polling_officer",
                      [stations["N1"]["id"], stations["N2"]["id"]])
        )
        receiver, _ = stack.enter_context(
            box_staff(admin, database_url, clock, "counting_officer", [stations["N1"]["id"]])
        )
        for reference, seal, local in (
            ("UI-N2-BOX-01", "UI-SEAL-01", False),
            ("UI-N1-LOCAL-01", "UI-LOCAL-SEAL-01", True),
            *[(f"API-N2-DYNAMIC-{index:02d}", f"API-DYNAMIC-SEAL-{index:02d}", False)
              for index in range(2, 6)],
        ):
            origin = target if local else source
            prepared = sender.post(
                origin,
                json=prepared_box(box_reference=reference, seal_reference=seal),
            )
            assert prepared.status_code == 201
            box_id = prepared.json()["id"]
            if not local:
                departed = sender.post(
                    f"{source}/{box_id}/departure",
                    json=event_command(
                        1, "2026-11-15T22:50:00+08:00",
                        reason="送箱紀錄第一行：已核對封條及票箱編號。\n第二行：合成運送流程，準備交收。",
                    ),
                )
                assert departed.status_code == 201
            received = receiver.post(
                f"{target}/{box_id}/receipt",
                json=event_command(
                    1 if local else 2, "2026-11-15T23:00:00+08:00",
                    reason="接收紀錄第一行：接收點已核對票箱及封條。\n第二行：保留原票站與送箱時間。",
                ),
            )
            assert received.status_code == 201
        statement = receiver.get(target + f"/statement?locale={locale}")
        assert statement.status_code == 200
        assert len(statement.json()["items"]) == 6
        assert len(statement.json()["box_history"]) == 17
        exported = receiver.get(target + f"/statement.pdf?locale={locale}")
        assert exported.status_code == 200
        (tmp_path / f"six-box-history-{locale}.pdf").write_bytes(exported.content)
        document = PdfReader(BytesIO(exported.content))
        pages = [page for page in document.pages if heading in page.extract_text()]
        assert len(pages) == 1
        spans: list[tuple[str, float]] = []

        def record_text(
            text: str, cm: list[float], tm: list[float], font: Any, size: float,
        ) -> None:
            if text.strip():
                spans.append((text.strip(), tm[4] * cm[1] + tm[5] * cm[3] + cm[5]))

        pages[0].extract_text(visitor_text=record_text)
        heading_y = next(y for text, y in spans if text == heading)
        below = [(text, y) for text, y in spans if y < heading_y]
        for expected in (reference_header, revision_header, "UI-N2-BOX-01", first_event):
            assert any(expected == text for text, _ in below), {
                "missing_below_heading": expected,
                "heading_page": document.pages.index(pages[0]) + 1,
                "text_below_heading": [text for text, _ in below],
            }
