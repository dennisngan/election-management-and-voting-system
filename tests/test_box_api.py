"""Ballot-box handovers and milestones through the real MySQL-backed API."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from election.server.app import create_app
from tests.box_support import BoxClock, box_staff, box_stations, event_command, prepared_box
from tests.lifecycle_support import lifecycle_database_url, lifecycle_test_state
from tests.polling_support import arrange_retained_polling_election


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    yield from lifecycle_database_url()


@pytest.fixture(autouse=True)
def clear_private_active_pointer(database_url: str) -> Iterator[None]:
    with lifecycle_test_state(database_url):
        yield


@pytest.fixture
def handed_box(admin: TestClient, database_url: str) -> Iterator[dict]:
    stations, clock = box_stations(admin), BoxClock()
    source = f"/api/workspace/stations/{stations['N2']['id']}/boxes"
    target = f"/api/workspace/stations/{stations['N1']['id']}/boxes"
    with box_staff(
        admin,
        database_url,
        clock,
        "polling_officer",
        [stations[key]["id"] for key in ("N1", "N2", "N3")],
    ) as (sender, po):
        with box_staff(
            admin,
            database_url,
            clock,
            "counting_officer",
            [stations[key]["id"] for key in ("N1", "N3", "S1")],
        ) as (receiver, co):
            body = prepared_box()
            prepared = sender.post(source, json=body)
            assert prepared.status_code == 201
            box_id = prepared.json()["id"]
            departure_body = event_command(1, "2026-11-15T22:45:00+08:00")
            departure = sender.post(f"{source}/{box_id}/departure", json=departure_body)
            assert departure.status_code == 201
            receipt = receiver.post(
                f"{target}/{box_id}/receipt", json=event_command(2, "2026-11-15T23:10:00+08:00")
            )
            assert receipt.status_code == 201
            yield {
                "stations": stations,
                "clock": clock,
                "source": source,
                "target": target,
                "sender": sender,
                "receiver": receiver,
                "po": po,
                "co": co,
                "box": receipt.json(),
                "prepared_body": body,
                "departure_body": departure_body,
                "departure": departure.json(),
            }


def test_assigned_officer_prepares_a_frozen_destination_box_without_inventing_count_data(
    admin: TestClient, database_url: str
) -> None:
    stations = box_stations(admin)
    origin, destination = stations["N2"], stations["N1"]
    clock = BoxClock()
    path = f"/api/workspace/stations/{origin['id']}/boxes"
    with box_staff(admin, database_url, clock, "polling_officer", [origin["id"]]) as (
        client,
        actor,
    ):
        response = client.post(path, json=prepared_box())
        assert response.status_code == 201
        row = response.json()
        assert row["origin_station_id"] == origin["id"]
        assert row["destination_station_id"] == destination["id"]
        assert row["mode"] == "send"
        assert row["box_reference"] == "票箱 0001"
        assert row["seal_reference"] == "封條 000099"
        assert row["prepared_at"] == "2026-11-15T14:40:00Z"
        assert row["entered_at"] == "2026-11-15T16:00:00Z"
        assert row["actor_id"] == actor["id"]
        assert row["revision"] == 1 and row["status"] == "prepared"
        assert row["departure_at"] is None and row["receipt_at"] is None
        snapshot = client.get(path)
        assert snapshot.status_code == 200
        assert snapshot.json()["items"] == [row]
        assert snapshot.json()["milestones"] == []
        assert snapshot.json()["milestone_history"] == []
        assert snapshot.json()["counting_applicable"] is False
        assert snapshot.json()["count_completion"] is None


def test_two_station_handover_keeps_origin_and_receiver_provenance_with_one_receipt(
    admin: TestClient, database_url: str
) -> None:
    stations = box_stations(admin)
    origin, destination = stations["N2"], stations["N1"]
    clock = BoxClock()
    source = f"/api/workspace/stations/{origin['id']}/boxes"
    target = f"/api/workspace/stations/{destination['id']}/boxes"
    with box_staff(admin, database_url, clock, "polling_officer", [origin["id"]]) as (sender, po):
        prepared = sender.post(source, json=prepared_box())
        assert prepared.status_code == 201
        box_id = prepared.json()["id"]
        departed = sender.post(
            f"{source}/{box_id}/departure",
            json=event_command(1, "2026-11-15T22:45:00+08:00"),
        )
        assert departed.status_code == 201
        assert departed.json()["revision"] == 2
        assert departed.json()["status"] == "departed"
        assert departed.json()["departure_at"] == "2026-11-15T14:45:00Z"
        assert departed.json()["departure"]["actor_id"] == po["id"]
        with box_staff(admin, database_url, clock, "counting_officer", [destination["id"]]) as (
            receiver,
            co,
        ):
            assert receiver.get(source).status_code == 403
            assert receiver.get(target).json()["items"] == [departed.json()]
            receipt_body = event_command(2, "2026-11-15T23:10:00+08:00")
            received = receiver.post(f"{target}/{box_id}/receipt", json=receipt_body)
            assert received.status_code == 201
            assert received.json()["revision"] == 3
            assert received.json()["status"] == "received"
            assert received.json()["receipt_at"] == "2026-11-15T15:10:00Z"
            assert received.json()["receipt"]["actor_id"] == co["id"]
            replay = receiver.post(f"{target}/{box_id}/receipt", json=receipt_body)
            assert replay.status_code == 200
            assert replay.json() == received.json()
            duplicate = receiver.post(
                f"{target}/{box_id}/receipt", json=event_command(3, "2026-11-15T23:10:00+08:00")
            )
            assert duplicate.status_code == 409
            assert duplicate.json()["detail"]["code"] == "box_state_conflict"
            history = receiver.get(f"{target}/{box_id}/history")
            assert history.status_code == 200
            events = history.json()["items"]
            assert [row["kind"] for row in events] == ["prepared", "departure", "receipt"]
            assert [row["actor_id"] for row in events] == [po["id"], po["id"], co["id"]]
            assert all(row["entered_at"] == "2026-11-15T16:00:00Z" for row in events)
            assert sender.get(source).json()["items"] == [received.json()]


def test_local_box_receipt_needs_no_departure_and_reasoned_correction_preserves_history(
    admin: TestClient, database_url: str
) -> None:
    station = box_stations(admin)["N1"]
    clock = BoxClock()
    path = f"/api/workspace/stations/{station['id']}/boxes"
    with box_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (po, _):
        prepare = prepared_box()
        created = po.post(path, json=prepare)
        assert created.status_code == 201
        original = created.json()
        box_id = original["id"]
        assert original["mode"] == "local"
        assert original["origin_station_id"] == original["destination_station_id"] == station["id"]
        prohibited = po.post(
            f"{path}/{box_id}/departure", json=event_command(1, "2026-11-15T22:45:00+08:00")
        )
        assert prohibited.status_code == 422
        with box_staff(admin, database_url, clock, "counting_officer", [station["id"]]) as (
            co,
            actor,
        ):
            received = co.post(
                f"{path}/{box_id}/receipt", json=event_command(1, "2026-11-15T22:45:00+08:00")
            )
            assert received.status_code == 201
            correction = event_command(
                2, "2026-11-15T22:46:00+08:00", reason="核對本地票箱接收紀錄更正一分鐘"
            )
            revised = co.put(f"{path}/{box_id}/receipt", json=correction)
            assert revised.status_code == 200
            assert revised.json()["revision"] == 3
            assert revised.json()["status"] == "received"
            assert revised.json()["departure_at"] is None
            assert revised.json()["receipt_at"] == "2026-11-15T14:46:00Z"
            assert revised.json()["receipt"]["kind"] == "receipt_correction"
            assert revised.json()["receipt"]["reason"] == correction["reason"]
            assert revised.json()["receipt"]["actor_id"] == actor["id"]
            assert co.put(f"{path}/{box_id}/receipt", json=correction).json() == revised.json()
            history = co.get(f"{path}/{box_id}/history").json()
            assert [row["kind"] for row in history["items"]] == [
                "prepared",
                "receipt",
                "receipt_correction",
            ]
            assert history["items"][1] == received.json()["receipt"]
            replay = po.post(path, json=prepare)
            assert replay.status_code == 200
            assert replay.json() == original
            assert co.get(path).json()["items"] == [revised.json()]


def test_counting_milestones_preserve_revisions_and_never_fabricate_count_completion(
    admin: TestClient, database_url: str
) -> None:
    station = box_stations(admin)["N1"]
    clock = BoxClock()
    path = f"/api/workspace/stations/{station['id']}/boxes"
    with box_staff(admin, database_url, clock, "polling_officer", [station["id"]]) as (po, _):
        created = po.post(path, json=prepared_box())
        assert created.status_code == 201
        box_id = created.json()["id"]
    with box_staff(admin, database_url, clock, "counting_officer", [station["id"]]) as (co, actor):
        received = co.post(
            f"{path}/{box_id}/receipt", json=event_command(1, "2026-11-15T22:45:00+08:00")
        )
        assert received.status_code == 201
        conversion = co.put(
            path + "/milestones/conversion_complete",
            json=event_command(0, "2026-11-15T22:41:00+08:00"),
        )
        assert conversion.status_code == 200
        first = co.put(
            path + "/milestones/first_box_opening",
            json=event_command(0, "2026-11-15T22:50:00+08:00", box_id=box_id),
        )
        assert first.status_code == 200
        assert first.json()["event_at"] == "2026-11-15T14:50:00Z"
        assert first.json()["entered_at"] == "2026-11-15T16:00:00Z"
        assert first.json()["station_id"] == station["id"]
        assert first.json()["box_id"] == box_id
        started = co.put(
            path + "/milestones/questionable_determination_start",
            json=event_command(0, "2026-11-15T23:00:00+08:00"),
        )
        assert started.status_code == 200
        assert started.json()["kind"] == "questionable_determination_start"
        assert started.json()["event_at"] == "2026-11-15T15:00:00Z"
        assert started.json()["box_id"] is None
        correction = event_command(
            1, "2026-11-15T22:55:00+08:00", box_id=box_id, reason="核對紙本第一票箱開啟時間"
        )
        changed = co.put(path + "/milestones/first_box_opening", json=correction)
        assert changed.status_code == 200
        assert changed.json()["revision"] == 2
        assert changed.json()["actor_id"] == actor["id"]
        assert changed.json()["reason"] == correction["reason"]
        replay = co.put(path + "/milestones/first_box_opening", json=correction)
        assert replay.status_code == 200 and replay.json() == changed.json()
        snapshot = co.get(path).json()
        assert snapshot["counting_applicable"] is True
        assert snapshot["milestones"] == [conversion.json(), changed.json(), started.json()]
        assert snapshot["milestone_history"] == [
            conversion.json(),
            first.json(),
            started.json(),
            changed.json(),
        ]
        assert snapshot["count_completion"] is None
        invalid_completion = co.put(
            path + "/milestones/count_completion",
            json=event_command(0, "2026-11-15T23:10:00+08:00"),
        )
        assert invalid_completion.status_code == 422
        later_receipt = co.put(
            f"{path}/{box_id}/receipt",
            json=event_command(2, "2026-11-15T23:10:00+08:00", reason="不可晚於已記錄開箱時間"),
        )
        assert later_receipt.status_code == 422
        later_conversion = co.put(
            path + "/milestones/conversion_complete",
            json=event_command(1, "2026-11-15T23:05:00+08:00", reason="不能破壞現有先後次序"),
        )
        assert later_conversion.status_code == 422
        assert co.get(path).json() == snapshot


@pytest.mark.parametrize(
    "changes",
    [
        {"box_reference": ""},
        {"box_reference": "   "},
        {"box_reference": "字" * 65},
        {"seal_reference": ""},
        {"seal_reference": " "},
        {"seal_reference": "字" * 129},
        {"prepared_at": "2026-11-15T16:00:01Z"},
        {"prepared_at": "2026-11-15T22:40:00"},
        {"prepared_at": "0001-01-01T00:00:00Z"},
        {"prepared_at": "0001-01-01T00:00:00+23:59"},
        {"prepared_at": "9999-12-31T23:59:59-23:59"},
        {"destination_station_id": 999},
        {"count_completion": "2026-11-15T23:30:00Z"},
    ],
)
def test_invalid_box_identity_time_or_destination_override_has_no_history_effect(
    handed_box: dict, changes: dict
) -> None:
    client, path = handed_box["sender"], handed_box["source"]
    before = client.get(path).json()
    body = prepared_box(box_reference="驗證用新票箱")
    body.update(changes)
    rejected = client.post(path, json=body)
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] in ("validation_error", "box_validation")
    assert client.get(path).json() == before


def test_box_references_are_origin_scoped_case_sensitive_and_identity_is_not_editable(
    handed_box: dict,
) -> None:
    client, path = handed_box["sender"], handed_box["source"]
    duplicate = client.post(path, json=prepared_box())
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "box_reference_exists"
    rows = []
    for reference in ("Box A", "box a"):
        response = client.post(path, json=prepared_box(box_reference=reference))
        assert response.status_code == 201
        rows.append(response.json())
    assert rows[0]["box_reference"] == "Box A" and rows[1]["box_reference"] == "box a"
    local_path = f"/api/workspace/stations/{handed_box['stations']['N3']['id']}/boxes"
    same_reference_other_origin = client.post(local_path, json=prepared_box())
    assert same_reference_other_origin.status_code == 201
    original = handed_box["box"]
    unsupported = client.put(f"{path}/{original['id']}", json={"box_reference": "Changed"})
    assert unsupported.status_code in (404, 405)
    assert client.get(f"{path}/{original['id']}/history").json()["box"] == original


def test_handover_corrections_require_fresh_revision_and_keep_known_chronology(
    handed_box: dict,
) -> None:
    sender, receiver = handed_box["sender"], handed_box["receiver"]
    box_id, source, target = handed_box["box"]["id"], handed_box["source"], handed_box["target"]
    history = sender.get(f"{source}/{box_id}/history").json()
    for client, path, at in (
        (sender, source + f"/{box_id}/departure", "2026-11-15T23:11:00+08:00"),
        (sender, source + f"/{box_id}/departure", "2026-11-15T22:39:00+08:00"),
        (receiver, target + f"/{box_id}/receipt", "2026-11-15T22:44:00+08:00"),
        (receiver, target + f"/{box_id}/receipt", "2026-11-15T16:00:01Z"),
    ):
        rejected = client.put(path, json=event_command(3, at, reason="核對但不能破壞先後次序"))
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "box_validation"
    corrected = sender.put(
        f"{source}/{box_id}/departure",
        json=event_command(3, "2026-11-15T22:46:00+08:00", reason="紙本離站時間更正一分鐘"),
    )
    assert corrected.status_code == 200
    assert corrected.json()["revision"] == 4 and corrected.json()["status"] == "received"
    assert corrected.json()["receipt"] == handed_box["box"]["receipt"]
    assert corrected.json()["departure_at"] == "2026-11-15T14:46:00Z"
    new_history = sender.get(f"{source}/{box_id}/history").json()
    assert new_history["items"][:3] == history["items"]
    replay = sender.post(f"{source}/{box_id}/departure", json=handed_box["departure_body"])
    assert replay.status_code == 200 and replay.json() == handed_box["departure"]
    stale = receiver.put(
        f"{target}/{box_id}/receipt",
        json=event_command(3, "2026-11-15T23:11:00+08:00", reason="舊版本不能覆寫"),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"
    assert sender.get(f"{source}/{box_id}/history").json() == new_history


@pytest.mark.parametrize(
    "changes",
    [
        {"reason": ""},
        {"reason": " "},
        {"reason": "字" * 1001},
        {"expected_revision": True},
        {"expected_revision": "3"},
        {"expected_revision": 0},
        {"event_at": "2026-11-15T23:11:00"},
    ],
)
def test_invalid_correction_shapes_do_not_replace_a_record(handed_box: dict, changes: dict) -> None:
    client, path = handed_box["receiver"], handed_box["target"]
    box_id = handed_box["box"]["id"]
    body = event_command(3, "2026-11-15T23:11:00+08:00", reason="核對原始票箱接收紀錄")
    body.update(changes)
    rejected = client.put(f"{path}/{box_id}/receipt", json=body)
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "validation_error"
    assert client.get(path).json()["items"] == [handed_box["box"]]


def test_missing_departure_wrong_destination_and_unreceived_box_cannot_be_acknowledged(
    handed_box: dict,
) -> None:
    sender, receiver = handed_box["sender"], handed_box["receiver"]
    original = handed_box["box"]
    for code in ("N3", "S1"):
        path = (
            f"/api/workspace/stations/{handed_box['stations'][code]['id']}/boxes/{original['id']}"
        )
        assert receiver.get(path + "/history").status_code == 404
        rejected = receiver.post(
            path + "/receipt", json=event_command(3, "2026-11-15T23:10:00+08:00")
        )
        assert rejected.status_code == 404
    prepared = sender.post(handed_box["source"], json=prepared_box(box_reference="尚未離站"))
    assert prepared.status_code == 201
    box_id = prepared.json()["id"]
    early_receipt = receiver.post(
        f"{handed_box['target']}/{box_id}/receipt",
        json=event_command(1, "2026-11-15T23:00:00+08:00"),
    )
    assert early_receipt.status_code == 409
    assert early_receipt.json()["detail"]["code"] == "box_departure_required"
    opening = receiver.put(
        handed_box["target"] + "/milestones/first_box_opening",
        json=event_command(0, "2026-11-15T23:10:00+08:00", box_id=box_id),
    )
    assert opening.status_code == 409
    assert opening.json()["detail"]["code"] == "box_receipt_required"
    history = sender.get(f"{handed_box['source']}/{box_id}/history").json()
    assert [row["kind"] for row in history["items"]] == ["prepared"]


def test_arrival_lists_are_dynamic_and_local_boxes_are_not_duplicated_in_the_snapshot(
    handed_box: dict,
) -> None:
    sender, receiver = handed_box["sender"], handed_box["receiver"]
    for number in range(2, 8):
        created = sender.post(
            handed_box["source"], json=prepared_box(box_reference=f"票箱 {number:04d}")
        )
        assert created.status_code == 201
        box_id = created.json()["id"]
        assert (
            sender.post(
                f"{handed_box['source']}/{box_id}/departure",
                json=event_command(1, "2026-11-15T22:45:00+08:00"),
            ).status_code
            == 201
        )
        assert (
            receiver.post(
                f"{handed_box['target']}/{box_id}/receipt",
                json=event_command(2, "2026-11-15T23:10:00+08:00"),
            ).status_code
            == 201
        )
    local = sender.post(handed_box["target"], json=prepared_box(box_reference="本站票箱"))
    assert local.status_code == 201
    assert (
        receiver.post(
            f"{handed_box['target']}/{local.json()['id']}/receipt",
            json=event_command(1, "2026-11-15T22:45:00+08:00"),
        ).status_code
        == 201
    )
    snapshot = receiver.get(handed_box["target"]).json()
    assert len(snapshot["items"]) == len({row["id"] for row in snapshot["items"]}) == 8
    assert sum(row["mode"] == "send" for row in snapshot["items"]) == 7
    assert all(row["status"] == "received" for row in snapshot["items"])
    assert snapshot["count_completion"] is None and snapshot["milestones"] == []


@pytest.mark.parametrize("role", ["polling_officer", "counting_officer", "supervisor"])
def test_station_roles_read_history_but_origin_and_destination_mutations_keep_their_roles(
    handed_box: dict, admin: TestClient, database_url: str, role: str
) -> None:
    sender = handed_box["sender"]
    origin, destination = handed_box["stations"]["N2"], handed_box["stations"]["N1"]
    source, target, clock = handed_box["source"], handed_box["target"], handed_box["clock"]
    outgoing = sender.post(source, json=prepared_box(box_reference="職務離站測試"))
    local = sender.post(target, json=prepared_box(box_reference="職務收箱測試"))
    assert outgoing.status_code == local.status_code == 201
    with box_staff(admin, database_url, clock, role, [origin["id"], destination["id"]]) as (
        client,
        _,
    ):
        assert client.get(source).status_code == client.get(target).status_code == 200
        assert client.get(f"{source}/{handed_box['box']['id']}/history").status_code == 200
        created = client.post(source, json=prepared_box(box_reference="另一職員準備的票箱"))
        departure = client.post(
            f"{source}/{outgoing.json()['id']}/departure",
            json=event_command(1, "2026-11-15T22:45:00+08:00"),
        )
        receipt = client.post(
            f"{target}/{local.json()['id']}/receipt",
            json=event_command(1, "2026-11-15T22:45:00+08:00"),
        )
        milestone = client.put(
            target + "/milestones/conversion_complete",
            json=event_command(0, "2026-11-15T22:35:00+08:00"),
        )
        assert (
            created.status_code
            == departure.status_code
            == (201 if role == "polling_officer" else 403)
        )
        assert receipt.status_code == (201 if role == "counting_officer" else 403)
        assert milestone.status_code == (200 if role == "counting_officer" else 403)
        wrong_station = f"/api/workspace/stations/{handed_box['stations']['N3']['id']}/boxes"
        assert client.get(wrong_station).status_code == 403
        assert client.get(wrong_station + f"/{handed_box['box']['id']}/history").status_code == 403


def test_anonymous_initial_password_and_administrator_have_no_operational_override(
    handed_box: dict, admin: TestClient, database_url: str
) -> None:
    source, target, clock = handed_box["source"], handed_box["target"], handed_box["clock"]
    box_id = handed_box["box"]["id"]

    def operations(client: TestClient) -> list:
        return [
            client.get(source),
            client.get(f"{source}/{box_id}/history"),
            client.post(source, json=prepared_box(box_reference="不可越權")),
            client.post(
                f"{source}/{box_id}/departure", json=event_command(3, "2026-11-15T22:45:00+08:00")
            ),
            client.post(
                f"{target}/{box_id}/receipt", json=event_command(3, "2026-11-15T23:10:00+08:00")
            ),
            client.put(
                f"{target}/{box_id}/receipt",
                json=event_command(3, "2026-11-15T23:11:00+08:00", reason="越權修正"),
            ),
            client.put(
                target + "/milestones/conversion_complete",
                json=event_command(0, "2026-11-15T22:35:00+08:00"),
            ),
        ]

    with TestClient(create_app(database_url, now=clock)) as anonymous:
        assert all(response.status_code == 401 for response in operations(anonymous))
    ids = [handed_box["stations"][code]["id"] for code in ("N1", "N2")]
    with box_staff(admin, database_url, clock, "polling_officer", ids, ready=False) as (initial, _):
        for response in operations(initial):
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "password_change_required"
    assert all(response.status_code == 403 for response in operations(admin))


def test_counting_station_and_received_box_are_required_only_where_applicable(
    handed_box: dict, admin: TestClient, database_url: str
) -> None:
    target, co, box_id = handed_box["target"], handed_box["receiver"], handed_box["box"]["id"]
    for kind, body in (
        ("first_box_opening", event_command(0, "2026-11-15T23:15:00+08:00")),
        ("first_box_opening", event_command(0, "2026-11-15T23:15:00+08:00", box_id=True)),
        ("first_box_opening", event_command(0, "2026-11-15T23:09:00+08:00", box_id=box_id)),
        ("conversion_complete", event_command(0, "2026-11-15T22:35:00+08:00", box_id=box_id)),
        (
            "questionable_determination_start",
            event_command(0, "2026-11-15T23:20:00+08:00", box_id=box_id),
        ),
    ):
        assert co.put(target + "/milestones/" + kind, json=body).status_code == 422
    assert co.get(target).json()["milestone_history"] == []
    origin_id = handed_box["stations"]["N2"]["id"]
    with box_staff(admin, database_url, handed_box["clock"], "counting_officer", [origin_id]) as (
        sending_co,
        _,
    ):
        rejected = sending_co.put(
            handed_box["source"] + "/milestones/conversion_complete",
            json=event_command(0, "2026-11-15T22:35:00+08:00"),
        )
        assert rejected.status_code == 403
        assert rejected.json()["detail"]["code"] == "counting_station_required"
    partial = co.put(
        target + "/milestones/questionable_determination_start",
        json=event_command(0, "2026-11-15T23:20:00+08:00"),
    )
    assert partial.status_code == 200
    snapshot = co.get(target).json()
    assert snapshot["milestones"] == [partial.json()] and snapshot["count_completion"] is None
    incompatible = co.put(
        target + "/milestones/conversion_complete",
        json=event_command(0, "2026-11-15T23:21:00+08:00"),
    )
    assert incompatible.status_code == 422
    conversion = co.put(
        target + "/milestones/conversion_complete",
        json=event_command(0, "2026-11-15T23:00:00+08:00"),
    )
    assert conversion.status_code == 200
    first = co.put(
        target + "/milestones/first_box_opening",
        json=event_command(0, "2026-11-15T23:15:00+08:00", box_id=box_id),
    )
    assert first.status_code == 200
    assert (
        co.put(
            target + "/milestones/first_box_opening",
            json=event_command(1, "2026-11-15T23:16:00+08:00", box_id=box_id),
        ).status_code
        == 422
    )
    stale = co.put(
        target + "/milestones/first_box_opening",
        json=event_command(0, "2026-11-15T23:16:00+08:00", box_id=box_id, reason="舊版本不能覆寫"),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"


@pytest.mark.parametrize("action", ["prepare", "departure", "receipt", "milestone"])
@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_commands_replay_one_effect_or_reject_the_second_writer(
    handed_box: dict, database_url: str, action: str, same_key: bool
) -> None:
    source, target = handed_box["source"], handed_box["target"]
    if action == "prepare":
        endpoint, method, client = source, "post", handed_box["sender"]
        body = prepared_box(box_reference="同時準備同一票箱")
    elif action == "milestone":
        endpoint, method, client = (
            target + "/milestones/conversion_complete",
            "put",
            handed_box["receiver"],
        )
        body = event_command(0, "2026-11-15T22:35:00+08:00")
    else:
        creation_path = source if action == "departure" else target
        created = handed_box["sender"].post(
            creation_path, json=prepared_box(box_reference="同時交接測試")
        )
        assert created.status_code == 201
        endpoint, method = f"{creation_path}/{created.json()['id']}/{action}", "post"
        client = handed_box["sender"] if action == "departure" else handed_box["receiver"]
        body = event_command(1, "2026-11-15T22:45:00+08:00")
    commands = [body, body if same_key else {**body, "request_id": str(uuid4())}]
    barrier = Barrier(2)

    def submit(command: dict) -> tuple[int, dict]:
        with TestClient(create_app(database_url, now=handed_box["clock"])) as peer:
            peer.headers.update(client.headers)
            barrier.wait(timeout=10)
            response = getattr(peer, method)(endpoint, json=command)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, commands))
    success_status = 200 if action == "milestone" else 201
    assert sorted(status for status, _ in outcomes) == sorted(
        [success_status, 200 if same_key else 409]
    )
    if same_key:
        assert outcomes[0][1] == outcomes[1][1]
    else:
        conflict = next(value for status, value in outcomes if status == 409)
        assert conflict["detail"]["code"] == (
            "box_reference_exists" if action == "prepare" else "revision_conflict"
        )
    winner = next(value for status, value in outcomes if status == success_status)
    if action == "milestone":
        assert client.get(target).json()["milestone_history"] == [winner]
    else:
        path = source if action in ("prepare", "departure") else target
        history = client.get(f"{path}/{winner['id']}/history").json()["items"]
        assert len(history) == (1 if action == "prepare" else 2)


def test_request_keys_bind_actor_station_action_and_box_target(
    handed_box: dict, admin: TestClient, database_url: str
) -> None:
    sender, source = handed_box["sender"], handed_box["source"]
    ids = []
    for reference in ("目標一", "目標二"):
        created = sender.post(source, json=prepared_box(box_reference=reference))
        assert created.status_code == 201
        ids.append(created.json()["id"])
    body = event_command(1, "2026-11-15T22:45:00+08:00")
    assert sender.post(f"{source}/{ids[0]}/departure", json=body).status_code == 201
    collision = sender.post(f"{source}/{ids[1]}/departure", json=body)
    assert collision.status_code == 409 and collision.json()["detail"]["code"] == "request_conflict"
    assert len(sender.get(f"{source}/{ids[1]}/history").json()["items"]) == 1
    changed_payload = sender.post(
        f"{source}/{ids[0]}/departure", json={**body, "reason": "同一要求不可換成其他內容"}
    )
    assert changed_payload.status_code == 409
    assert changed_payload.json()["detail"]["code"] == "request_conflict"
    same_instant = sender.post(
        source, json={**handed_box["prepared_body"], "prepared_at": "2026-11-15T14:40:00Z"}
    )
    assert same_instant.status_code == 200 and same_instant.json()["revision"] == 1
    milestone_body = event_command(0, "2026-11-15T23:20:00+08:00")
    conversion = handed_box["receiver"].put(
        handed_box["target"] + "/milestones/conversion_complete", json=milestone_body
    )
    assert conversion.status_code == 200
    other_action = handed_box["receiver"].put(
        handed_box["target"] + "/milestones/questionable_determination_start", json=milestone_body
    )
    assert other_action.status_code == 409
    assert other_action.json()["detail"]["code"] == "request_conflict"
    assert handed_box["receiver"].get(handed_box["target"]).json()["milestones"] == [
        conversion.json()
    ]
    with box_staff(
        admin,
        database_url,
        handed_box["clock"],
        "polling_officer",
        [handed_box["stations"]["N2"]["id"]],
    ) as (other_actor, _):
        collision = other_actor.post(source, json=handed_box["prepared_body"])
        assert (
            collision.status_code == 409
            and collision.json()["detail"]["code"] == "request_conflict"
        )
    global_body = prepared_box(box_reference="跨站要求識別碼")
    other_path = f"/api/workspace/stations/{handed_box['stations']['N3']['id']}/boxes"
    barrier = Barrier(2)

    def create_at(path: str) -> tuple[int, dict]:
        with TestClient(create_app(database_url, now=handed_box["clock"])) as peer:
            peer.headers.update(sender.headers)
            barrier.wait(timeout=10)
            response = peer.post(path, json=global_body)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(create_at, [source, other_path]))
    assert sorted(status for status, _ in outcomes) == [201, 409]
    assert (
        next(value for status, value in outcomes if status == 409)["detail"]["code"]
        == "request_conflict"
    )


def test_box_history_survives_restart_and_finalized_or_other_active_elections_reject_writes(
    handed_box: dict, admin: TestClient, database_url: str
) -> None:
    sender, receiver, clock = handed_box["sender"], handed_box["receiver"], handed_box["clock"]
    source, target, box_id = handed_box["source"], handed_box["target"], handed_box["box"]["id"]
    original = receiver.get(target).json()
    with TestClient(create_app(database_url, now=clock)) as restarted:
        restarted.headers.update(receiver.headers)
        assert restarted.get(target).json() == original
    # Arrange retained history only; this does not test Ticket 24's finalization workflow.
    arrange_retained_polling_election(database_url, handed_box["stations"]["election"]["id"])
    retained = receiver.get(target)
    assert retained.status_code == 200
    assert retained.json()["context"]["election"]["status"] == "finalized"
    assert retained.json()["items"] == original["items"]
    for response in (
        sender.post(source, json=prepared_box(box_reference="完成後不可新增")),
        sender.put(
            f"{source}/{box_id}/departure",
            json=event_command(3, "2026-11-15T22:46:00+08:00", reason="完成後不可修訂"),
        ),
        receiver.put(
            f"{target}/{box_id}/receipt",
            json=event_command(3, "2026-11-15T23:11:00+08:00", reason="完成後不可修訂"),
        ),
        receiver.put(
            target + "/milestones/conversion_complete",
            json=event_command(0, "2026-11-15T22:35:00+08:00"),
        ),
    ):
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "active_election_required"
    box_stations(admin)
    assert receiver.get(target).json()["items"] == original["items"]
    blocked = sender.post(source, json=prepared_box(box_reference="另一選舉進行中"))
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "active_election_required"


def test_draft_election_is_readable_but_cannot_prepare_boxes(
    admin: TestClient, database_url: str
) -> None:
    stations, clock = box_stations(admin, activate=False), BoxClock()
    station_id = stations["N1"]["id"]
    path = f"/api/workspace/stations/{station_id}/boxes"
    with box_staff(admin, database_url, clock, "polling_officer", [station_id]) as (client, _):
        assert client.get(path).status_code == 200
        assert client.get(path).json()["items"] == []
        rejected = client.post(path, json=prepared_box())
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "active_election_required"


def test_receiver_snapshots_and_sender_preparation_do_not_deadlock_or_lose_boxes(
    handed_box: dict, database_url: str
) -> None:
    sender, receiver = handed_box["sender"], handed_box["receiver"]
    source, target = handed_box["source"], handed_box["target"]
    for number in range(10):
        response = sender.post(source, json=prepared_box(box_reference=f"讀取負載票箱-{number}"))
        assert response.status_code == 201
    created_ids = {row["id"] for row in receiver.get(target).json()["items"]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for number in range(20):
            barrier = Barrier(2)
            body = prepared_box(box_reference=f"並行建立票箱-{number}")

            def read_snapshot() -> tuple[int, dict]:
                with TestClient(create_app(database_url, now=handed_box["clock"])) as peer:
                    peer.headers.update(receiver.headers)
                    barrier.wait(timeout=10)
                    response = peer.get(target)
                    return response.status_code, response.json()

            def prepare() -> tuple[int, dict]:
                with TestClient(create_app(database_url, now=handed_box["clock"])) as peer:
                    peer.headers.update(sender.headers)
                    barrier.wait(timeout=10)
                    response = peer.post(source, json=body)
                    return response.status_code, response.json()

            pending_read = pool.submit(read_snapshot)
            pending_write = pool.submit(prepare)
            read_status, snapshot = pending_read.result()
            write_status, box = pending_write.result()
            assert read_status == 200
            assert write_status == 201
            ids = [row["id"] for row in snapshot["items"]]
            assert len(ids) == len(set(ids))
            assert created_ids.issubset(ids)
            created_ids.add(box["id"])
    final = receiver.get(target)
    assert final.status_code == 200
    assert {row["id"] for row in final.json()["items"]} == created_ids
    assert len(created_ids) == 31


def test_documented_box_reference_lengths_remain_available_with_unicode(handed_box: dict) -> None:
    reference, seal = "票" * 64, "封" * 128
    response = handed_box["sender"].post(
        handed_box["source"], json=prepared_box(box_reference=reference, seal_reference=seal)
    )
    assert response.status_code == 201
    assert response.json()["box_reference"] == reference
    assert response.json()["seal_reference"] == seal
