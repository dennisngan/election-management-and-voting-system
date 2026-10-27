"""Public journal persistence under a verified non-UTF-8 process locale."""

import json
import os
import subprocess
import sys
from pathlib import Path

# ASCII-only command source survives the child's actual ASCII argument decoding.
# At runtime the escapes become genuine Chinese strings, written by CommandJournal.
CHILD = r"""
import codecs
import json
import locale
import os
import sys
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

report = {"fixture_available": False, "steps": {}, "read_errors": []}

def emit():
    wire = json.dumps(report, ensure_ascii=True, sort_keys=True) + "\n"
    sys.stdout.buffer.write(wire.encode("ascii"))
    sys.stdout.buffer.flush()

try:
    with open(os.devnull, "r") as probe:
        actual_encoding = probe.encoding
    report.update(
        utf8_mode=sys.flags.utf8_mode,
        lc_ctype=locale.setlocale(locale.LC_CTYPE),
        locale_encoding=locale.getencoding(),
        preferred_encoding=locale.getpreferredencoding(False),
        default_text_encoding=actual_encoding,
        filesystem_encoding=sys.getfilesystemencoding(),
    )
    series = "\u666e\u901a\u7cfb\u5217\u7532"
    reason = "\u6838\u5c0d\u7d19\u672c\u5f8c\u66f4\u6b63\u5e8f\u865f"
    encoding_name = codecs.lookup(actual_encoding).name
    rejects_chinese = False
    try:
        (series + reason).encode(actual_encoding, errors="strict")
    except UnicodeEncodeError:
        rejects_chinese = True
    report["default_codec"] = encoding_name
    report["default_rejects_chinese"] = rejects_chinese
    if sys.flags.utf8_mode != 0 or encoding_name == "utf-8" or not rejects_chinese:
        raise RuntimeError("non_utf8_locale_fixture_unavailable")
    if report["lc_ctype"] not in {"C", "POSIX"}:
        raise RuntimeError("requested_C_locale_not_active")
    report["fixture_available"] = True

    # Force the frozen checkout's source, independently of editable-install state.
    import election.desktop.client_command_journal as journal_module
    from election.desktop.client_command_journal import CommandJournal
    from election.private_paths import private_directory, private_file

    root, directory = Path(sys.argv[1]), Path(sys.argv[2])
    expected_module = root / "src/election/desktop/client_command_journal.py"
    assert Path(journal_module.__file__).resolve() == expected_module.resolve()
    origin, actor_id, station_id = "https://localhost:8479", 19, 7
    request_id = str(uuid4())
    assert str(UUID(request_id)) == request_id
    path = "/api/workspace/stations/7/allocations/11"
    safe_payload = {
        "request_id": request_id, "counter_id": 3, "series": series,
        "serial_from": "000001", "serial_to": "000002",
        "event_at": "2026-11-15T09:00:00+08:00", "revision": 1, "reason": reason,
    }
    # This sentinel tests the public journal's credential-filtering input policy.
    # It is not an account credential or a submitted HTTP allocation command.
    transient = "journal-ephemeral-input-must-not-persist"
    payload = {**deepcopy(safe_payload), "password": transient}
    original_input = deepcopy(payload)
    receipt = {
        "id": 11, "station_id": station_id, "revision": 2, "status": "recorded",
        "counter": {"id": 3, "code": "C1", "name": series},
        "series": series, "serial_from": "000001", "serial_to": "000002",
        "quantity": 2, "reason": reason,
        "event_at": "2026-11-15T01:00:00Z", "entered_at": "2026-11-15T04:00:00Z",
        "actor_id": actor_id,
    }
    journal = CommandJournal(directory)
    assert not directory.exists()
    prepared = journal.prepare(origin, actor_id, station_id, "allocation", path, "PUT", payload)
    assert payload == original_input
    assert prepared["request_id"] == request_id and prepared["status"] == "pending"
    assert prepared["payload"] == safe_payload and prepared["confirmation_required"] is True
    files = list(directory.glob("*.json"))
    assert len(files) == 1
    assert private_directory(directory) and private_file(files[0])
    raw = files[0].read_bytes()
    assert series.encode("utf-8") in raw and reason.encode("utf-8") in raw
    assert transient.encode("ascii") not in raw
    report["steps"]["prepare_utf8"] = True

    def attempt_read(name, action):
        try:
            value = action()
        except UnicodeError as error:
            report["read_errors"].append({
                "step": name, "type": type(error).__name__, "detail": str(error),
            })
            report["steps"][name] = False
            return None
        report["steps"][name] = True
        return value

    # Observe both faulty public read paths before the final failing assertion.
    # No alternate decode/read/write is substituted when either operation fails.
    pending = attempt_read(
        "commands_pending", lambda: CommandJournal(directory).commands(origin, actor_id, station_id)
    )
    attempt_read(
        "record_outcome",
        lambda: CommandJournal(directory).record_outcome(
            origin, actor_id, request_id, "committed", record=receipt,
        ),
    )
    committed = attempt_read(
        "commands_committed",
        lambda: CommandJournal(directory).commands(origin, actor_id, station_id),
    )
    assert not report["read_errors"], "journal_locale_decode_failed"
    assert pending == [prepared]
    assert len(committed) == 1
    settled = committed[0]
    assert settled["request_id"] == request_id
    assert settled["server_url"] == origin and settled["actor_id"] == actor_id
    assert settled["station_id"] == station_id and settled["workflow"] == "allocation"
    assert settled["path"] == path and settled["method"] == "PUT"
    assert settled["payload"] == safe_payload
    assert settled["status"] == "committed" and settled["error"] == ""
    assert settled["receipt"] == {"record": receipt}
    assert settled["created_at"] == prepared["created_at"] and settled["updated_at"]
    assert payload == original_input
    # Re-instantiation and the public replay must preserve the same identity and body.
    replayed = CommandJournal(directory).prepare(
        origin, actor_id, station_id, "allocation", path, "PUT", payload,
    )
    assert replayed == settled
    again = CommandJournal(directory).commands(origin, actor_id, station_id)
    assert again == committed
    assert len(list(directory.glob("*.json"))) == 1
    persisted = files[0].read_bytes()
    assert series.encode("utf-8") in persisted and reason.encode("utf-8") in persisted
    assert transient.encode("ascii") not in persisted
    serialized = json.dumps(again, ensure_ascii=True)
    assert transient not in serialized
    assert '"password"' not in serialized and '"authorization"' not in serialized
    assert private_directory(directory) and private_file(files[0])
    report["steps"]["canonical_committed_reload"] = True
    report["steps"]["same_uuid_body_replay"] = True
    report["steps"]["credential_free"] = True
    report["ok"] = True
except Exception as error:
    report["ok"] = False
    report["failure"] = {"type": type(error).__name__, "detail": str(error)}
    emit()
    raise SystemExit(1)
else:
    emit()
"""


def test_command_journal_chinese_payload_and_receipt_survive_real_non_utf8_locale(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONUTF8": "0",
        "PYTHONPATH": str(root / "src"),
    }
    assert CHILD.isascii(), "The child source must survive real ASCII command-line decoding"
    result = subprocess.run(
        [sys.executable, "-X", "utf8=0", "-c", CHILD, str(root), str(tmp_path / "commands")],
        cwd=root,
        env=environment,
        capture_output=True,
        check=False,
    )
    assert result.stdout.isascii(), "Child diagnostics must use ASCII JSON"
    diagnostic = json.loads(result.stdout.decode("ascii"))
    # If C is still UTF-8 on this interpreter/platform, this is a fixture failure,
    # never a silent skip, a fabricated encoding, or evidence of the journal defect.
    assert diagnostic["fixture_available"] is True, diagnostic
    assert result.returncode == 0, {
        "diagnostic": diagnostic,
        "stderr": result.stderr.decode("ascii", errors="backslashreplace"),
    }
    assert diagnostic["ok"] is True
    assert diagnostic["utf8_mode"] == 0
    assert diagnostic["default_codec"] != "utf-8"
    assert diagnostic["default_rejects_chinese"] is True
    assert diagnostic["read_errors"] == []
    assert all(diagnostic["steps"].values())
