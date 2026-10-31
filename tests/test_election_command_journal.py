"""Election command identity remains immutable after a local rejected outcome."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from election.desktop.client_command_journal import CommandJournal, JournalError
from election.private_paths import private_directory, private_file


def test_rejected_election_command_cannot_replace_its_original_payload(tmp_path: Path) -> None:
    origin, actor_id, election_id = "https://localhost:8479", 19, 7
    request_id = str(uuid4())
    path = "/api/workspace/elections/7/finalizations"
    original_payload = {
        "request_id": request_id, "expected_election_revision": 2, "basis_digest": "a" * 64,
    }
    directory = tmp_path / "election-commands"
    evidence = tmp_path / "rejected-election-identity-evidence"
    evidence.mkdir(mode=0o700)
    journal = CommandJournal(directory)
    prepared = journal.prepare_election(
        origin, actor_id, election_id, path, "POST", original_payload,
    )
    assert prepared["namespace"] == "election" and "station_id" not in prepared
    assert prepared["election_id"] == election_id and prepared["request_id"] == request_id
    assert prepared["payload"] == original_payload and prepared["status"] == "pending"
    journal.record_outcome(origin, actor_id, request_id, "rejected", error="revision_conflict")
    original_rows = journal.election_commands(origin, actor_id, election_id)
    assert len(original_rows) == 1
    original = original_rows[0]
    assert original["status"] == "rejected" and original["error"] == "revision_conflict"
    assert original["path"] == path and original["payload"] == original_payload
    files = list(directory.glob("*.json"))
    assert len(files) == 1
    journal_file = files[0]
    assert private_directory(directory) and private_file(journal_file)
    before = journal_file.read_bytes()
    descriptor = os.open(
        evidence / "original-rejected-command.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
    )
    with os.fdopen(descriptor, "wb") as output:
        output.write(before)
        output.flush()
        os.fsync(output.fileno())

    changed_payload = {**original_payload, "expected_election_revision": 3}
    actual_error: Exception | None = None
    returned = None
    try:
        returned = journal.prepare_election(
            origin, actor_id, election_id, path, "POST", changed_payload,
        )
    except Exception as error:
        # Preserve the actual verdict before asserting its expected public error.
        actual_error = error
    after = journal_file.read_bytes()
    descriptor = os.open(
        evidence / "after-changed-body-attempt.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
    )
    with os.fdopen(descriptor, "wb") as output:
        output.write(after)
        output.flush()
        os.fsync(output.fileno())
    after_rows = journal.election_commands(origin, actor_id, election_id)
    observed = {
        "boundary": "public CommandJournal filesystem adapter; no HTTP or server commit",
        "request_id": request_id, "actor_id": actor_id, "election_id": election_id,
        "original_expected_revision": 2, "attempted_expected_revision": 3,
        "actual_error_type": type(actual_error).__name__ if actual_error is not None else None,
        "actual_error_code": str(actual_error) if isinstance(actual_error, JournalError) else None,
        "returned_status": returned.get("status") if isinstance(returned, dict) else None,
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "after_sha256": hashlib.sha256(after).hexdigest(),
        "same_bytes": before == after, "after_rows": after_rows,
    }
    descriptor = os.open(
        evidence / "observed-attempt.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(observed, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())

    # Intended RED: rejected currently skips identity comparison and rewrites revision3.
    assert isinstance(actual_error, JournalError), observed
    assert str(actual_error) == "recovery_command_conflict", observed
    assert after == before
    assert after_rows == original_rows
    assert json.loads(after)["payload"] == original_payload
    assert json.loads(after)["status"] == "rejected"
    assert list(directory.glob("*.json")) == [journal_file]
    assert private_directory(directory) and private_file(journal_file)
    assert (evidence / "original-rejected-command.json").read_bytes() == before
    assert (evidence / "after-changed-body-attempt.json").read_bytes() == after
