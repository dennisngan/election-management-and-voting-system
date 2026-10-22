"""Assigned station selection uses public Qt slots over real HTTPS/MySQL."""

from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import ready_setup, save_form, setup_idle
from tests.desktop_support import TLS_DIRECTORY, HttpsServer, state_of, wait_for


def test_officer_selects_only_assigned_station_context_and_sign_out_clears_it(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    configuration = ready_setup(desktop, https_server, account, qt_app)
    election = save_form(configuration, qt_app, "election", {"name": "票站工作區桌面測試"})
    constituency = save_form(
        configuration, qt_app, "constituency", {"name": "工作區選區", "code": "WORKSPACE"}
    )
    stations = [
        save_form(
            configuration,
            qt_app,
            "station",
            {"name": f"工作區票站 {number}", "code": f"WS{number}"},
        )
        for number in (1, 2, 3)
    ]
    staff = desktop.property("staff")
    assert staff is not None
    staff.open()
    wait_for(qt_app, lambda: setup_idle(staff))
    username = "workspace_officer_" + uuid4().hex[:12]
    temporary_password = "Workspace-Initial-Password-42!"
    personal_password = "Workspace-Personal-Password-84!"
    assert staff.loadAccount(0, False)
    staff.setField("username", username)
    staff.setField("display_name", "工作區投票站職員")
    staff.setField("role", "polling_officer")
    for station in stations[:2]:
        staff.setStationAssigned(station["id"], True)
    staff.save(temporary_password, temporary_password)
    wait_for(qt_app, lambda: setup_idle(staff))
    assert staff.property("state")["error"] == ""
    assert staff.property("state")["selected"]["station_ids"] == [
        station["id"] for station in stations[:2]
    ]

    officer = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        officer.signIn(https_server.url, username, temporary_password)
        wait_for(qt_app, lambda: state_of(officer)["phase"] == "password_change")
        officer.changePassword(temporary_password, personal_password, personal_password)
        wait_for(qt_app, lambda: state_of(officer)["phase"] == "workspace")
        workspace = officer.property("workspace")
        assert workspace is not None
        workspace.open()
        wait_for(qt_app, lambda: setup_idle(workspace))
        available = workspace.property("state")
        assert available["error"] == ""
        assert {row["station"]["id"] for row in available["contexts"]} == {
            station["id"] for station in stations[:2]
        }
        assert available["selected"] == {}
        assert state_of(officer)["election"] is None
        assert state_of(officer)["constituency"] is None
        assert state_of(officer)["station"] is None
        assert state_of(officer)["capabilities"] == {}

        workspace.selectStation(stations[0]["id"])
        wait_for(qt_app, lambda: setup_idle(workspace))
        selected = workspace.property("state")["selected"]
        assert workspace.property("state")["error"] == ""
        assert selected["election"]["id"] == election["id"]
        assert selected["constituency"]["id"] == constituency["id"]
        assert selected["station"]["id"] == stations[0]["id"]
        assert selected["account"]["username"] == username
        assert selected["capabilities"] == {
            "prepare_polling": True,
            "prepare_counting": False,
            "approve": False,
        }
        for key in ("election", "constituency", "station", "capabilities"):
            assert state_of(officer)[key] == selected[key]

        workspace.selectStation(stations[2]["id"])
        wait_for(qt_app, lambda: setup_idle(workspace))
        rejected = workspace.property("state")
        assert rejected["error"] == "station_access_denied"
        assert rejected["selected"] == selected
        assert rejected["contexts"] == available["contexts"]
        for key in ("election", "constituency", "station", "capabilities"):
            assert state_of(officer)[key] == selected[key]

        workspace.refresh()
        wait_for(qt_app, lambda: setup_idle(workspace))
        assert workspace.property("state")["selected"] == selected
        assert {row["station"]["id"] for row in workspace.property("state")["contexts"]} == {
            station["id"] for station in stations[:2]
        }
        officer.signOut()
        assert state_of(officer)["phase"] == "signed_out"
        assert state_of(officer)["account"] == {}
        assert state_of(officer)["election"] is None
        assert state_of(officer)["constituency"] is None
        assert state_of(officer)["station"] is None
        assert state_of(officer)["capabilities"] == {}
        assert workspace.property("state") == {
            "contexts": [],
            "selected": {},
            "busy": False,
            "refreshing": False,
            "error": "",
            "notice": "",
        }
    finally:
        officer.shutdown()
        officer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()
