"""Station arrangements use the shared desktop editor and real Qt HTTPS/MySQL."""

from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from election.desktop.controller import DesktopController
from tests.configuration_desktop_support import ready_setup, save_form, setup_idle
from tests.desktop_support import (
    PERSONAL_PASSWORD,
    TLS_DIRECTORY,
    HttpsServer,
    state_of,
    wait_for,
)


def test_desktop_reopens_four_stations_counters_and_same_constituency_destination(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> None:
    setup = ready_setup(desktop, https_server, account, qt_app)
    election = save_form(setup, qt_app, "election", {"name": "四票站桌面測試"})
    constituencies: list[dict] = []
    stations: dict[int, list[dict]] = {}
    counters: dict[int, dict] = {}
    for code, name in (("N", "北區"), ("S", "南區")):
        constituency = save_form(setup, qt_app, "constituency", {"name": name, "code": code})
        constituencies.append(constituency)
        stations[constituency["id"]] = []
        assert setup.property("state")["selected"]["candidate"] == {}
        for number in (1, 2):
            sending = code == "N" and number == 2
            receiver_id = stations[constituency["id"]][0]["id"] if sending else None
            station = save_form(
                setup,
                qt_app,
                "station",
                {
                    "name": f"  {name}票站 {number}  ",
                    "code": f"{code}{number}",
                    "counting_mode": "send" if sending else "local",
                    "destination_station_id": str(receiver_id) if sending else "",
                },
            )
            assert station["election_id"] == election["id"]
            assert station["constituency_id"] == constituency["id"]
            assert station["counting_mode"] == ("send" if sending else "local")
            assert station["destination_station_id"] == receiver_id
            assert station["name"] == f"  {name}票站 {number}  "
            stations[constituency["id"]].append(station)
            counter = save_form(
                setup,
                qt_app,
                "counter",
                {"name": name + f"票站 {number} 發票櫃台", "code": "C1"},
            )
            assert counter["election_id"] == election["id"]
            assert counter["constituency_id"] == constituency["id"]
            assert counter["station_id"] == station["id"]
            counters[station["id"]] = counter
            assert setup.property("state")["selected"]["candidate"] == {}
    assert sum(len(rows) for rows in stations.values()) == 4
    setup.refresh()
    wait_for(qt_app, lambda: setup_idle(setup))
    assert setup.load("election", election["id"], False)
    wait_for(qt_app, lambda: setup_idle(setup))
    for constituency in constituencies:
        assert setup.load("constituency", constituency["id"], False)
        wait_for(qt_app, lambda: setup_idle(setup))
        state = setup.property("state")
        assert {row["id"] for row in state["stations"]} == {
            row["id"] for row in stations[constituency["id"]]
        }
        assert state["selected"]["station"] == {}
        assert state["selected"]["counter"] == {}
        assert state["candidates"] == []
        for station in stations[constituency["id"]]:
            assert setup.load("station", station["id"], False)
            wait_for(qt_app, lambda: setup_idle(setup))
            state = setup.property("state")
            assert state["selected"]["station"] == station
            assert state["forms"]["station"]["counting_mode"] == station["counting_mode"]
            assert state["forms"]["station"]["destination_station_id"] == (
                str(station["destination_station_id"])
                if station["destination_station_id"] is not None
                else ""
            )
            assert state["counters"] == [counters[station["id"]]]
            assert setup.load("counter", counters[station["id"]]["id"], False)
            wait_for(qt_app, lambda: setup_idle(setup))
            state = setup.property("state")
            assert state["selected"]["counter"] == counters[station["id"]]
            assert state["forms"]["counter"]["name"] == counters[station["id"]]["name"]
            assert state["dirty"]["station"] is False
            assert state["dirty"]["counter"] is False


@pytest.fixture
def station_setup(
    desktop: DesktopController,
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
) -> tuple[Any, dict]:
    setup = ready_setup(desktop, https_server, account, qt_app)
    election = save_form(setup, qt_app, "election", {"name": "票站桌面行為測試"})
    constituency = save_form(setup, qt_app, "constituency", {"name": "北區", "code": "N"})
    receiver = save_form(setup, qt_app, "station", {"name": "北區接收站", "code": "N1"})
    alternate = save_form(setup, qt_app, "station", {"name": "北區另一接收站", "code": "N3"})
    sender = save_form(
        setup,
        qt_app,
        "station",
        {
            "name": "北區送箱站",
            "code": "N2",
            "counting_mode": "send",
            "destination_station_id": str(receiver["id"]),
        },
    )
    counter = save_form(setup, qt_app, "counter", {"name": "原有發票櫃台", "code": "C1"})
    return setup, {
        "election": election,
        "constituency": constituency,
        "receiver": receiver,
        "alternate": alternate,
        "sender": sender,
        "counter": counter,
    }


@pytest.mark.parametrize("locale", ["tc", "sc", "en"])
def test_sending_destination_validation_is_localized_and_switching_local_clears_it(
    desktop: DesktopController,
    https_server: HttpsServer,
    qt_app: QCoreApplication,
    station_setup: tuple[Any, dict],
    locale: str,
) -> None:
    setup, rows = station_setup
    desktop.setLocale(locale)
    assert setup.load("station", 0, False)
    setup.setField("station", "name", "  保留票站名稱  ")
    setup.setField("station", "code", "NEW")
    setup.setField("station", "counting_mode", "send")
    path = (
        f"/api/elections/{rows['election']['id']}/constituencies/"
        f"{rows['constituency']['id']}/stations"
    )
    posts_before = https_server.request_count("POST", path)
    localized = {"tc": "必須選擇接收站", "sc": "必须选择接收站", "en": "receiving station"}
    for destination in ("", "0", "-1", "1.5", "station", "9" * 5000):
        setup.setField("station", "destination_station_id", destination)
        setup.save("station")
        state = setup.property("state")
        assert state["error"] == "station_configuration_validation"
        assert state["busy"] is False
        assert state["forms"]["station"]["name"] == "  保留票站名稱  "
        assert state["forms"]["station"]["destination_station_id"] == destination
        assert localized[locale] in desktop.property("texts")[state["error"]]
    setup.refresh()
    wait_for(qt_app, lambda: setup_idle(setup))
    assert https_server.request_count("POST", path) == posts_before
    setup.setField("station", "destination_station_id", str(rows["receiver"]["id"]))
    setup.setField("station", "counting_mode", "local")
    assert setup.property("state")["forms"]["station"]["destination_station_id"] == ""
    setup.save("station")
    wait_for(qt_app, lambda: setup_idle(setup))
    saved = setup.property("state")["selected"]["station"]
    assert saved["name"] == "  保留票站名稱  "
    assert saved["counting_mode"] == "local"
    assert saved["destination_station_id"] is None


def test_candidate_edits_preserve_dirty_station_siblings_and_constituency_switch_requires_discard(
    qt_app: QCoreApplication, station_setup: tuple[Any, dict]
) -> None:
    setup, rows = station_setup
    other_constituency = save_form(setup, qt_app, "constituency", {"name": "南區", "code": "S"})
    assert setup.load("constituency", rows["constituency"]["id"], False)
    wait_for(qt_app, lambda: setup_idle(setup))
    assert setup.load("station", rows["sender"]["id"], False)
    wait_for(qt_app, lambda: setup_idle(setup))
    assert setup.load("counter", rows["counter"]["id"], False)
    wait_for(qt_app, lambda: setup_idle(setup))
    candidate = save_form(setup, qt_app, "candidate", {"name": "原有候選人", "ballot_number": "1"})
    setup.setField("station", "name", "票站未儲存名稱")
    setup.setField("counter", "name", "櫃台未儲存名稱")
    assert setup.load("candidate", candidate["id"], False)
    wait_for(qt_app, lambda: setup_idle(setup))
    setup.setField("candidate", "name", "候選人已修訂")
    setup.save("candidate")
    wait_for(qt_app, lambda: setup_idle(setup))
    before = setup.property("state")
    assert before["selected"]["candidate"]["name"] == "候選人已修訂"
    assert before["forms"]["station"]["name"] == "票站未儲存名稱"
    assert before["forms"]["counter"]["name"] == "櫃台未儲存名稱"
    assert before["selected"]["station"] == rows["sender"]
    assert before["selected"]["counter"] == rows["counter"]
    assert before["dirty"]["station"] is before["dirty"]["counter"] is True
    assert setup.load("constituency", other_constituency["id"], False) is False
    assert setup.property("state") == before
    assert setup.load("constituency", other_constituency["id"], True)
    wait_for(qt_app, lambda: setup_idle(setup))
    after = setup.property("state")
    assert after["selected"]["constituency"] == other_constituency
    for kind in ("station", "counter"):
        assert after["selected"][kind] == {}
        assert after["forms"][kind]["name"] == ""
        assert after["dirty"][kind] is False
        assert after["editing"][kind] is False
    assert after["stations"] == []
    assert after["counters"] == []


def test_receiver_in_use_error_preserves_form_until_explicit_saved_reload(
    desktop: DesktopController,
    qt_app: QCoreApplication,
    station_setup: tuple[Any, dict],
) -> None:
    setup, rows = station_setup
    assert setup.load("station", rows["receiver"]["id"], False)
    wait_for(qt_app, lambda: setup_idle(setup))
    setup.setField("station", "name", "嘗試改為送箱站的未儲存名稱")
    setup.setField("station", "counting_mode", "send")
    setup.setField("station", "destination_station_id", str(rows["alternate"]["id"]))
    setup.save("station")
    wait_for(qt_app, lambda: setup_idle(setup))
    state = setup.property("state")
    assert state["error"] == "receiver_in_use"
    assert "其他投票站已指定送往此站" in desktop.property("texts")[state["error"]]
    assert state["forms"]["station"]["name"] == "嘗試改為送箱站的未儲存名稱"
    assert state["forms"]["station"]["counting_mode"] == "send"
    assert state["forms"]["station"]["destination_station_id"] == str(rows["alternate"]["id"])
    assert state["selected"]["station"] == rows["receiver"]
    assert state["dirty"]["station"] is True
    assert setup.load("station", rows["receiver"]["id"], False) is False
    assert setup.load("station", rows["receiver"]["id"], True)
    wait_for(qt_app, lambda: setup_idle(setup))
    reloaded = setup.property("state")
    assert reloaded["error"] == ""
    assert reloaded["selected"]["station"] == rows["receiver"]
    assert reloaded["forms"]["station"]["name"] == rows["receiver"]["name"]
    assert reloaded["forms"]["station"]["counting_mode"] == "local"
    assert reloaded["forms"]["station"]["destination_station_id"] == ""
    assert reloaded["dirty"]["station"] is False


def test_second_desktop_refreshes_new_station_and_counter_while_preserving_local_form(
    https_server: HttpsServer,
    account: dict[str, str],
    qt_app: QCoreApplication,
    station_setup: tuple[Any, dict],
) -> None:
    setup, rows = station_setup
    second = DesktopController(https_server.url, str(TLS_DIRECTORY / "ca.pem"))
    try:
        second.signIn(https_server.url, account["username"], PERSONAL_PASSWORD)
        wait_for(qt_app, lambda: state_of(second)["phase"] == "workspace")
        other = second.property("configuration")
        for kind, row in (
            ("election", rows["election"]),
            ("constituency", rows["constituency"]),
            ("station", rows["sender"]),
        ):
            assert other.load(kind, row["id"], False)
            wait_for(qt_app, lambda: setup_idle(other))
        assert other.load("counter", 0, False)
        other.setField("counter", "name", "另一桌面未儲存櫃台")
        other.setField("counter", "code", "DRAFT")
        new_counter = save_form(setup, qt_app, "counter", {"name": "新共用櫃台", "code": "C2"})
        new_station = save_form(setup, qt_app, "station", {"name": "新共用票站", "code": "N4"})
        other.refresh()
        wait_for(qt_app, lambda: setup_idle(other))
        state = other.property("state")
        assert any(row == new_station for row in state["stations"])
        assert any(row == new_counter for row in state["counters"])
        assert state["selected"]["station"] == rows["sender"]
        assert state["selected"]["counter"] == {}
        assert state["forms"]["counter"] == {"name": "另一桌面未儲存櫃台", "code": "DRAFT"}
        assert state["dirty"]["counter"] is True
    finally:
        second.shutdown()
        second.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()
