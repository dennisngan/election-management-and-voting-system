"""Actual Material P(15) source controls use the live TLS/MySQL workflows."""

import csv
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.desktop_support import HttpsServer
from tests.fallback_support import (
    approved_mixed_period,
    confirm_fallback_activation,
    fallback_setup,
)
from tests.qml_workspace_support import run_workspace_qml
from tests.test_fallback_activation_api import database_url as database_url
from tests.test_fallback_activation_api import private_active_election as private_active_election
from tests.turnout_support import READY_PASSWORD, turnout_command


def test_material_selects_fallback_sources_and_supervisor_approves_mixed_115(
    admin: TestClient, database_url: str, https_server: HttpsServer,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        activation = confirm_fallback_activation(setup)
        observed = setup["officer"].post(setup["base"] + "/stock-snapshots", json={
            "request_id": str(uuid4()), "event_at": "2026-11-15T12:00:00+08:00",
            "counters": [{"counter_id": setup["counter_id"], "ranges": [{
                "series": "普通系列 A", "serial_from": "000116", "serial_to": "000200",
            }]}],
        })
        assert observed.status_code == 201
        endpoint = observed.json()
        assert endpoint["ordinary_issued_quantity"] == 115
        assert endpoint["ordinary_remaining_quantity"] == 85
        https_server.clock.value = setup["clock"].value
        run_workspace_qml(
            {"server": https_server.url, "username": setup["account"]["username"],
             "password": READY_PASSWORD, "station_id": endpoint["station_id"], "locale": "tc",
             "activation_id": activation["id"], "snapshot_id": endpoint["id"],
             "supervisor_username": setup["supervisor_account"]["username"]},
            """
            click('turnoutNavigation')
            turnout = controller.property('turnout')
            def idle():
                return not any(turnout.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            choose('turnoutPeriodPicker', 1)
            wait(idle)
            assert turnout.property('state')['selected_period'] == 2
            # First new UI boundary: this source selector is missing in RED.
            assert control('turnoutSourceMode').property('currentIndex') == 0
            choose('turnoutSourceMode', 1)
            assert control('turnoutSourceMode').property('displayText') == '後備普通庫存推算'
            assert control('turnoutHourly').property('readOnly') is True
            assert control('turnoutCumulative').property('readOnly') is True
            enter('turnoutFallbackActivationId', str(setup['activation_id']))
            enter('turnoutFallbackActivationRevision', '1')
            enter('turnoutStockSnapshotId', str(setup['snapshot_id']))
            enter('turnoutStockSnapshotRevision', '1')
            enter('turnoutEventTime', '2026-11-15 12:00')
            enter('turnoutSource', '已確認110人加其後五張普通發票。')
            click('turnoutSave')
            wait(idle)
            assert turnout.property('state')['error'] == ''
            assert turnout.property('state')['selected']['provenance'] == 'mixed'
            assert control('turnoutBaselineValue').property('text') == '110'
            assert control('turnoutOrdinaryDeltaValue').property('text') == '5'
            assert control('turnoutStockCumulativeValue').property('text') == '115'
            assert '100 → 110' in control('turnoutCoverage0Value').property('text')
            assert '110 → 115' in control('turnoutCoverage1Value').property('text')
            click('turnoutSubmit')
            wait(idle)
            assert turnout.property('state')['selected']['status'] == 'submitted'
            controller.signOut()
            wait(lambda: controller.property('state')['phase'] == 'signed_out')
            frame()
            controller.signIn(setup['server'], setup['supervisor_username'], setup['password'])
            wait(lambda: controller.property('state')['phase'] == 'workspace')
            workspace = controller.property('workspace')
            workspace.open()
            wait(lambda: not workspace.property('state')['busy'])
            workspace.selectStation(setup['station_id'])
            wait(lambda: not workspace.property('state')['busy'])
            click('turnoutNavigation')
            wait(idle)
            choose('turnoutPeriodPicker', 1)
            wait(idle)
            assert control('turnoutSourceMode').property('enabled') is False
            assert control('turnoutFallbackActivationId').property('readOnly') is True
            assert control('turnoutBaselineValue').property('text') == '110'
            enter('turnoutApprovalPassword', setup['password'])
            click('turnoutApprove')
            wait(idle)
            assert turnout.property('state')['error'] == ''
            assert turnout.property('state')['selected']['derived_hourly_display'] == '15'
            assert turnout.property('state')['selected']['derived_cumulative_end_display'] == '115'
            """,
        )
        current = setup["officer"].get(setup["scope"]["path"])
        assert current.status_code == 200
        assert current.json()["approved_prefix"]["cumulative_end"] == 115


@pytest.mark.parametrize("locale,mode_label", [
    ("tc", "恢復外部數字核對"),
    ("sc", "恢复外部数字核对"),
    ("en", "Reconciled external recovery"),
], ids=["tc", "sc", "en"])
def test_material_recovery_selection_preserves_history_and_exports_saved_revisions(
    admin: TestClient, database_url: str, https_server: HttpsServer,
    tmp_path: Path, locale: str, mode_label: str,
) -> None:
    with fallback_setup(admin, database_url) as setup:
        prepared = approved_mixed_period(setup)
        activation, endpoint, original = (
            prepared["activation"], prepared["endpoint"], prepared["approved"]
        )
        officer = setup["officer"]
        created = officer.post(setup["path"], json={
            "request_id": str(uuid4()), "expected_schedule_revision": 1, "kind": "recovery",
            "activation_id": activation["id"], "activation_revision": 1,
            "event_at": "2026-11-15T12:00:00+08:00", "cumulative_quantity": 116,
            "stock_snapshot_id": endpoint["id"], "stock_snapshot_revision": 1,
            "source_context": "Recovered manual register confirms 116 at noon.",
            "reason": "Reconcile to 116 rather than adding the stock-derived 115.",
        })
        assert created.status_code == 201
        recovery = created.json()
        recovery_path = setup["path"] + f"/{recovery['id']}"
        assert officer.post(recovery_path + "/submit", json=turnout_command(1)).status_code == 200
        confirmed = setup["supervisor"].post(
            recovery_path + "/approve", json=turnout_command(1, password=READY_PASSWORD),
        )
        assert confirmed.status_code == 200
        https_server.clock.value = setup["clock"].value
        run_workspace_qml(
            {"server": https_server.url, "username": setup["account"]["username"],
             "password": READY_PASSWORD, "station_id": endpoint["station_id"], "locale": locale,
             "recovery_id": recovery["id"], "mode_label": mode_label,
             "supervisor_username": setup["supervisor_account"]["username"],
             "output_directory": str(tmp_path)},
            """
            from PySide6.QtCore import QObject
            click('turnoutNavigation')
            turnout = controller.property('turnout')
            def idle():
                return not any(turnout.property('state')[key] for key in ('busy', 'refreshing'))
            wait(idle)
            choose('turnoutPeriodPicker', 1)
            wait(idle)
            choose('turnoutSourceMode', 2)
            assert control('turnoutSourceMode').property('displayText') == setup['mode_label']
            # First new recovery UI boundary: the exact-text recovery selector is missing.
            enter('turnoutFallbackRecoveryId', str(setup['recovery_id']))
            enter('turnoutFallbackRecoveryRevision', '1')
            assert control('turnoutHourly').property('readOnly') is False
            assert control('turnoutHourly').property('text') == ''
            assert control('turnoutCumulative').property('text') == ''
            enter('turnoutEventTime', '2026-11-15 12:00')
            enter('turnoutSource', 'Material recovered source 116')
            enter('turnoutAmendmentReason', 'Renew against the confirmed recovery revision.')
            click('turnoutAmend')
            wait(idle)
            assert turnout.property('state')['error'] == ''
            assert turnout.property('state')['selected']['revision'] == 2
            assert turnout.property('state')['selected']['provenance'] == 'external_reconciled'
            assert control('turnoutStockCumulativeValue').property('text') == '115'
            assert control('turnoutRecoveredCumulativeValue').property('text') == '116'
            assert control('turnoutReconciliationDifferenceValue').property('text') == '1'
            assert '110 → 116' in control('turnoutCoverage1Value').property('text')
            click('turnoutSubmit')
            wait(idle)
            controller.signOut()
            wait(lambda: controller.property('state')['phase'] == 'signed_out')
            frame()
            controller.signIn(setup['server'], setup['supervisor_username'], setup['password'])
            wait(lambda: controller.property('state')['phase'] == 'workspace')
            workspace = controller.property('workspace')
            workspace.open()
            wait(lambda: not workspace.property('state')['busy'])
            workspace.selectStation(setup['station_id'])
            wait(lambda: not workspace.property('state')['busy'])
            click('turnoutNavigation')
            wait(idle)
            choose('turnoutPeriodPicker', 1)
            wait(idle)
            enter('turnoutApprovalPassword', setup['password'])
            click('turnoutApprove')
            wait(idle)
            assert turnout.property('state')['error'] == ''
            assert turnout.property('state')['selected']['derived_cumulative_end_display'] == '116'
            assert turnout.property('state')['selected']['derived_hourly_display'] == '16'

            def export_saved(format, stem):
                dialog = window.findChild(QObject, 'turnoutExportDialog')
                assert dialog is not None
                dialog.setProperty('currentFolder', QUrl.fromLocalFile(setup['output_directory']))
                click('turnoutExportCsv' if format == 'csv' else 'turnoutExportPdf')
                wait(lambda: dialog.property('visible'))
                filename = stem + '.' + format
                field = focus('fileNameTextField')
                assert QMetaObject.invokeMethod(field, 'selectAll')
                dialog_window = field.window()
                QCoreApplication.sendEvent(dialog_window, QKeyEvent(QEvent.Type.KeyPress, 0,
                    Qt.KeyboardModifier.NoModifier, filename))
                QCoreApplication.sendEvent(dialog_window, QKeyEvent(QEvent.Type.KeyRelease, 0,
                    Qt.KeyboardModifier.NoModifier, ''))
                application.processEvents()
                assert field.property('text') == filename
                pending = list(dialog_window.contentItem().childItems())
                buttons = []
                while pending:
                    item = pending.pop()
                    text = str(item.property('text') or '').replace('&', '')
                    if (item.inherits('QQuickAbstractButton') and item.property('visible')
                            and text in ('Save', '儲存', '保存')):
                        buttons.append(item)
                    pending.extend(item.childItems())
                assert len(buttons) == 1, 'The actual save dialog needs one visible Save button'
                button = buttons[0]
                center = button.mapToScene(QPointF(button.width()/2, button.height()/2)).toPoint()
                QTest.mouseClick(button.window(), Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier, center)
                wait(lambda: not dialog.property('visible'))
                window.requestActivate()
                wait(lambda: window.isActive())
                wait(idle)
                assert turnout.property('state')['error'] == ''
                assert turnout.property('state')['export_path'] == str(
                    Path(setup['output_directory']) / (stem + '.' + format))

            choose('turnoutReportScope', 0)
            click('turnoutPreview')
            wait(idle)
            report = turnout.property('state')['report']
            assert report['revision'] == 2 and report['revision_state'] == 'current'
            assert report['locale'] == setup['locale']
            export_saved('csv', 'current-' + setup['locale'])
            export_saved('pdf', 'current-' + setup['locale'])
            click('turnoutHistoryRevision1')
            wait(idle)
            assert turnout.property('state')['historical'] is True
            assert control('turnoutSourceMode').property('currentIndex') == 1
            assert control('turnoutSourceMode').property('enabled') is False
            assert control('turnoutStockCumulativeValue').property('text') == '115'
            click('turnoutPreview')
            wait(idle)
            report = turnout.property('state')['report']
            assert report['revision'] == 1 and report['revision_state'] == 'historical'
            assert report['items'][0]['derived_cumulative_end'] == 115
            export_saved('csv', 'historical-' + setup['locale'])
            export_saved('pdf', 'historical-' + setup['locale'])
            choose('turnoutReportScope', 1)
            click('turnoutPreview')
            wait(idle)
            report = turnout.property('state')['report']
            assert report['report_scope'] == 'station_current'
            assert report['approved_prefix']['cumulative_end'] == 116
            assert turnout.property('state')['selected']['revision'] == 1
            """,
        )
        for stem, revision, cumulative, hourly, context in (
            ("current", 2, "116", "16", "Material recovered source 116"),
            ("historical", 1, "115", "15", original["source_context"]),
        ):
            report_response = officer.get(
                setup["scope"]["path"] + "/2/statement",
                params={"revision": revision, "locale": locale},
            )
            assert report_response.status_code == 200
            labels = report_response.json()["labels"]
            csv_path = tmp_path / f"{stem}-{locale}.csv"
            assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
            with csv_path.open(encoding="utf-8-sig", newline="") as exported:
                rows = list(csv.reader(exported))
            assert [labels["derived_cumulative_end"], cumulative] in rows
            assert [labels["derived_hourly"], hourly] in rows
            assert [labels["source_context"], context] in rows
            pdf_path = tmp_path / f"{stem}-{locale}.pdf"
            assert pdf_path.read_bytes().startswith(b"%PDF")
            text = "\n".join(page.extract_text() for page in PdfReader(pdf_path).pages)
            assert cumulative in text and labels["derived_cumulative_end"] in text
            assert context[:20] in text
        retained = officer.get(setup["scope"]["path"] + "/2?revision=1")
        assert retained.status_code == 200 and retained.json() == original
