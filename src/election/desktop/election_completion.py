"""Reviewed election completion and durable original command acknowledgements."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest
from election.desktop.event_times import format_event_time
from election.desktop.exact_numbers import qt_state, quantity_display
from election.desktop.operational_receipts import valid_operational_receipt
from election.desktop.recovery import NETWORK_ERRORS, RecoveryController
from election.desktop.report_files import DownloadRequest, report_destination, save_report


class ElectionCompletionController(QObject):
    stateChanged = Signal()
    finalized = Signal(object)
    reopened = Signal(object)

    def __init__(
        self, request: AuthorizedRequest, parent: QObject | None = None, *,
        recovery: RecoveryController | None = None, download: DownloadRequest | None = None,
    ) -> None:
        super().__init__(parent)
        self._request, self._recovery = request, recovery
        self._download = download
        self._generation = 0
        self._report_generation = 0
        self._opened = False
        self._scope: tuple[Any, ...] | None = None
        self._state: dict[str, Any] = {}
        self.reset()
        if recovery is not None:
            recovery.stateChanged.connect(self._sync_recovery)

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        view = quantity_display(self._state)
        view["can_finalize"] = self._can_finalize(self._state["assessment"])
        view["can_reopen"] = bool(self._reopening_basis())
        view["selected_event"] = quantity_display(self._selected_event())
        view["history_event_times"] = {
            str(event["id"]): format_event_time(event.get("accepted_at"))
            for event in self._state["history"].get("events", [])
        }
        receipt = self._state["receipt"]
        if (
            self._recovery is not None and receipt
            and not self._recovery.election_receipt_disclosed(receipt["request_id"])
        ):
            view["receipt"] = {}
        return qt_state(view)

    def _selected_event(self) -> dict[str, Any]:
        return next((event for event in self._state["history"].get("events", [])
                     if event.get("id") == self._state["selected_event_id"]), {})

    def _clear_report(self) -> None:
        self._report_generation += 1
        self._state.update(report={}, report_text="", export_path="")

    def _can_finalize(self, assessment: dict[str, Any]) -> bool:
        election_id = self._state["election_id"]
        reviewed = assessment.get("election") or {}
        current = self._state["election"]
        return bool(
            self._state["role"] == "supervisor"
            and type(election_id) is int and election_id > 0
            and assessment.get("can_finalize") is True
            and reviewed.get("id") == election_id and reviewed.get("status") == "active"
            and type(reviewed.get("revision")) is int and reviewed["revision"] > 0
            and current.get("id") == election_id and current.get("status") == "active"
            and ("name" not in current or current["name"] == reviewed.get("name"))
            and (type(current.get("revision")) is not int
                 or current["revision"] == reviewed["revision"])
        )

    def _observe_election(self, election: dict[str, Any]) -> None:
        """Keep the newest version observed within the current authenticated scope."""
        if election.get("id") != self._state["election_id"]:
            return
        known_revision = self._state["election"].get("revision")
        revision = election.get("revision")
        if type(known_revision) is int and (
            type(revision) is not int or revision < known_revision
        ):
            return
        self._state["election"] = deepcopy(election)
        if self._state["reviewing"] and not self._can_finalize(self._state["review"]):
            self._state["newer_basis"] = True
        self._observe_reopening_review()

    def reset(self) -> None:
        self._generation += 1
        self._report_generation += 1
        self._opened = False
        self._scope = None
        self._command: dict[str, Any] | None = None
        self._receipt_disclosed = True
        self._state = {
            "election_id": None, "actor_id": None, "role": "", "election": {},
            "assessment": {}, "busy": False, "refreshing": False, "error": "",
            "receipt": {}, "pending_request_id": "", "uncertain_save": False,
            "reconciling": False, "review": {}, "reviewing": False, "newer_basis": False,
            "history": {}, "selected_event_id": None,
            "reopening_review": {}, "reopening_changed": False,
            "report": {}, "report_text": "", "export_path": "", "notice": "",
        }
        self.stateChanged.emit()

    def set_context(
        self, account: dict[str, Any], election: dict[str, Any] | None, origin: str
    ) -> None:
        target = election or {}
        election_id = target.get("id")
        scope = (origin, account.get("id"), election_id, account.get("role", ""))
        changed = scope != self._scope
        if changed:
            opened = self._opened
            self.reset()
            self._opened = opened
        self._scope = scope
        self._state.update(
            election_id=election_id, actor_id=account.get("id"),
            role=account.get("role", ""),
        )
        self._observe_election(target)
        self._sync_recovery()
        self.stateChanged.emit()
        if changed and self._opened:
            self.refresh()

    @Slot()
    def open(self) -> None:
        self._opened = True
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        election_id = self._state["election_id"]
        if (
            not self._opened or self._state["busy"] or self._state["refreshing"]
            or self._state["role"] != "supervisor"
            or type(election_id) is not int or election_id <= 0
            or type(self._state["actor_id"]) is not int
        ):
            return
        generation = self._generation
        self._state.update(refreshing=True, error="")
        self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            self._state.update(refreshing=False, error=code)
            self.stateChanged.emit()

        def loaded(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if (
                not isinstance(data.get("election"), dict)
                or data["election"].get("id") != election_id
                or type(data.get("can_finalize")) is not bool
                or not isinstance(data.get("blockers"), list)
                or not all(isinstance(row, dict) for row in data["blockers"])
                or not isinstance(data.get("sources"), dict)
            ):
                failed("request_failed")
                return
            self._observe_election(data["election"])
            review = self._state["review"]
            if self._state["reviewing"] and (
                data["election"] != review["election"]
                or data.get("basis_digest") != review.get("basis_digest")
                or data["can_finalize"] is not True
            ):
                self._state["newer_basis"] = True
            self._state.update(assessment=deepcopy(data), refreshing=False, error="")
            self.stateChanged.emit()

        self._request(
            f"/api/workspace/elections/{election_id}/completion", "GET", None, loaded, failed
        )

    @Slot()
    def loadHistory(self) -> None:
        election_id = self._state["election_id"]
        if (
            self._state["role"] != "supervisor" or self._state["busy"]
            or self._state["refreshing"] or type(election_id) is not int or election_id <= 0
        ):
            return
        generation = self._generation
        self._state.update(refreshing=True, error="")
        self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            self._state.update(refreshing=False, error=code)
            if code == "full_election_access_required":
                self._state.update(history={}, selected_event_id=None)
                self._clear_report()
            self.stateChanged.emit()

        def loaded(data: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if (
                not isinstance(data.get("election"), dict)
                or data["election"].get("id") != election_id
                or not isinstance(data.get("events"), list)
                or not all(
                    isinstance(event, dict) and event.get("election_id") == election_id
                    and event.get("kind") in {"finalization", "reopening"}
                    and isinstance(event.get("outcome"), dict)
                    for event in data["events"]
                )
            ):
                failed("invalid_response")
                return
            self._observe_election(data["election"])
            selected_id = self._state["selected_event_id"]
            if not any(event.get("id") == selected_id for event in data["events"]):
                selected_id = data["events"][0]["id"] if data["events"] else None
                self._clear_report()
            self._state.update(
                history=deepcopy(data), selected_event_id=selected_id,
                refreshing=False, error="",
            )
            self._observe_reopening_review()
            self.stateChanged.emit()

        self._request(
            f"/api/workspace/elections/{election_id}/completion/history",
            "GET", None, loaded, failed,
        )

    @Slot(str)
    def selectHistoryEvent(self, event_id: str) -> None:
        if self._state["busy"] or self._state["role"] != "supervisor":
            return
        try:
            target = int(event_id)
        except ValueError:
            return
        if target <= 0 or not any(
            event.get("id") == target for event in self._state["history"].get("events", [])
        ):
            return
        if target != self._state["selected_event_id"]:
            self._clear_report()
            self._state.update(selected_event_id=target, error="")
            self.stateChanged.emit()

    @Slot(str)
    def preview(self, locale: str) -> None:
        event = deepcopy(self._selected_event())
        if (
            self._state["role"] != "supervisor" or not event
            or locale not in {"tc", "sc", "en"}
            or self._state["busy"] or self._state["refreshing"]
        ):
            return
        self._clear_report()
        generation, report_generation = self._generation, self._report_generation
        self._state.update(busy=True, error="")
        self.stateChanged.emit()

        def current() -> bool:
            return (
                generation == self._generation
                and report_generation == self._report_generation
                and self._state["selected_event_id"] == event["id"]
            )

        def failed(code: str) -> None:
            if current():
                self._state.update(busy=False, error=code)
                self.stateChanged.emit()

        def loaded(body: dict[str, Any]) -> None:
            if not current():
                return
            rows = body.get("rows")
            if (
                body.get("locale") != locale or body.get("event") != event
                or not isinstance(body.get("tables"), list) or not isinstance(rows, list)
                or not all(
                    isinstance(row, list) and all(isinstance(value, str) for value in row)
                    for row in rows
                )
            ):
                failed("invalid_response")
                return
            self._state.update(
                busy=False, report=deepcopy(body),
                report_text="\n".join(" · ".join(row) for row in rows), error="",
            )
            self.stateChanged.emit()

        self._request(
            f"/api/workspace/elections/{self._state['election_id']}"
            f"/completion/history/{event['id']}/statement?locale={locale}",
            "GET", None, loaded, failed,
        )

    @Slot(str, str, str)
    def exportReport(self, locale: str, format: str, filepath: str) -> None:
        if self._state["busy"] or self._state["refreshing"]:
            return
        event = deepcopy(self._selected_event())
        destination = report_destination(filepath)
        if (
            self._state["role"] != "supervisor" or not event
            or locale not in {"tc", "sc", "en"} or format not in {"csv", "pdf"}
            or self._download is None or destination is None
        ):
            self._state.update(error="election_completion_export_failed", notice="")
            self.stateChanged.emit()
            return
        self._report_generation += 1
        generation, report_generation = self._generation, self._report_generation
        self._state.update(busy=True, error="", notice="", export_path="")
        self.stateChanged.emit()

        def current() -> bool:
            return (
                generation == self._generation
                and report_generation == self._report_generation
                and self._state["selected_event_id"] == event["id"]
            )

        def failed(code: str) -> None:
            if current():
                self._state.update(busy=False, error=code, notice="")
                self.stateChanged.emit()

        def loaded(body: dict[str, Any]) -> None:
            if not current():
                return
            if not save_report(body, destination, format):
                failed("election_completion_export_failed")
                return
            self._state.update(
                busy=False, error="", notice="election_completion_exported",
                export_path=destination,
            )
            self.stateChanged.emit()

        self._download(
            f"/api/workspace/elections/{self._state['election_id']}"
            f"/completion/history/{event['id']}/statement.{format}?locale={locale}",
            loaded, failed,
        )

    def wait_for_current_lifecycle(self) -> Callable[[str], None]:
        """Keep settlement visibly working until an authoritative lifecycle read finishes."""
        generation = self._generation
        self._state.update(refreshing=True, reconciling=True)
        self.stateChanged.emit()

        def finished(code: str) -> None:
            if generation != self._generation:
                return
            self._state.update(refreshing=False, reconciling=False, error=code)
            self.stateChanged.emit()

        return finished

    def _settled(self, body: dict[str, Any]) -> None:
        self._generation += 1
        self._command = None
        assessment = self._state["assessment"]
        election = assessment.get("election")
        # A recovered receipt must not replace an already observed live revision.
        if (
            not isinstance(election, dict) or election.get("id") != body["election"]["id"]
            or type(election.get("revision")) is not int
            or election["revision"] < body["election"]["revision"]
        ):
            election = body["election"]
            assessment = {
                **assessment, "election": deepcopy(election),
                "active_election_id": body["active_election_id"], "can_finalize": False,
            }
        self._observe_election(election)
        self._state.update(
            busy=False, refreshing=False, receipt=deepcopy(body), pending_request_id="",
            uncertain_save=False, error="",
            assessment=deepcopy(assessment), review={}, reviewing=False, newer_basis=False,
            reopening_review={}, reopening_changed=False,
        )
        # Start authoritative reconciliation before observers can see settlement as idle.
        if body["event"]["kind"] == "reopening":
            self.reopened.emit(body)
        else:
            self.finalized.emit(body)
        self.stateChanged.emit()

    def _sync_recovery(self) -> None:
        if self._recovery is None:
            return
        receipt = self._state["receipt"]
        disclosed = not receipt or self._recovery.election_receipt_disclosed(receipt["request_id"])
        if disclosed != self._receipt_disclosed:
            self._receipt_disclosed = disclosed
            self.stateChanged.emit()
        if self._state["role"] != "supervisor" or not self._scope:
            return
        pending_id = self._state["pending_request_id"]
        command = next((row for row in self._recovery.command_records() if (
            row.get("namespace") == "election" and row.get("workflow") == "election_completion"
            and row.get("election_id") == self._state["election_id"]
            and row.get("actor_id") == self._state["actor_id"]
            and row.get("server_url") == self._scope[0]
            and row.get("path") in {
                f"/api/workspace/elections/{self._state['election_id']}/finalizations",
                f"/api/workspace/elections/{self._state['election_id']}/reopenings",
            }
            and (row.get("request_id") == pending_id if pending_id
                 else row.get("status") in {"pending", "uncertain"})
        )), None)
        if command is None:
            return
        if command.get("status") in {"pending", "uncertain"}:
            if self._command is None:
                self._command = deepcopy(command)
            self._state.update(
                uncertain_save=True, pending_request_id=command["request_id"],
                error=command.get("error") or "",
            )
            self.stateChanged.emit()
        elif command.get("status") == "committed":
            receipt = (command.get("receipt") or {}).get("record")
            if isinstance(receipt, dict) and valid_operational_receipt(
                self._command or command, receipt,
            ):
                self._settled(receipt)
        elif command.get("status") == "rejected":
            self._command = None
            self._state.update(
                uncertain_save=False, pending_request_id="",
                error=command.get("error") or "election_completion_not_ready",
            )
            self.stateChanged.emit()

    @Slot(result=bool)
    def prepareFinalization(self) -> bool:
        assessment = self._state["assessment"]
        if (
            self._state["busy"] or self._state["refreshing"] or self._state["uncertain_save"]
            or not self._can_finalize(assessment)
        ):
            self._state["error"] = "election_completion_not_ready"
            self.stateChanged.emit()
            return False
        self._state.update(
            review=deepcopy(assessment), reviewing=True, newer_basis=False, error="",
        )
        self.stateChanged.emit()
        return True

    @Slot()
    def cancelReview(self) -> None:
        if (
            self._state["busy"] or self._state["uncertain_save"]
            or not self._state["reviewing"]
        ):
            return
        self._state.update(review={}, reviewing=False, newer_basis=False, error="")
        self.stateChanged.emit()

    @Slot(str)
    def finalize(self, password: str) -> None:
        if self._state["newer_basis"]:
            self._state["error"] = "election_completion_review_changed"
            self.stateChanged.emit()
            return
        assessment = (
            self._state["review"] if self._state["reviewing"] else self._state["assessment"]
        )
        if (
            self._state["busy"] or self._state["refreshing"] or self._state["uncertain_save"]
            or not self._can_finalize(assessment)
        ):
            self._state["error"] = "election_completion_not_ready"
            self.stateChanged.emit()
            return
        if not password:
            self._state["error"] = "invalid_credentials"
            self.stateChanged.emit()
            return
        payload = {
            "request_id": str(uuid4()),
            "expected_election_revision": assessment["election"]["revision"],
            "basis_digest": assessment["basis_digest"],
        }
        self._save_election_command("finalizations", payload, password)

    def _reopening_basis(self) -> dict[str, Any]:
        election_id = self._state["election_id"]
        current = self._state["election"]
        history = self._state["history"]
        election = history.get("election") or {}
        events = history.get("events") or []
        previous = events[0] if events else {}
        if (
            self._state["role"] != "supervisor"
            or type(election_id) is not int or election_id <= 0
            or current.get("status") != "finalized"
            or election.get("id") != election_id or election.get("status") != "finalized"
            or type(election.get("revision")) is not int
            or type(current.get("revision")) is int
            and current["revision"] != election["revision"]
            or history.get("active_election_id") not in {None, election_id}
            or previous.get("election_id") != election_id
            or previous.get("kind") != "finalization"
            or previous.get("election_revision") != election["revision"]
            or type(previous.get("id")) is not int or previous["id"] <= 0
        ):
            return {}
        return {
            "election_id": election_id, "expected_election_revision": election["revision"],
            "previous_finalization_id": previous["id"],
        }

    def _observe_reopening_review(self) -> None:
        review = self._state["reopening_review"]
        if review and self._reopening_basis() != {
            key: value for key, value in review.items() if key != "reason"
        }:
            self._state["reopening_changed"] = True

    @Slot(str, result=bool)
    def prepareReopening(self, reason: str) -> bool:
        basis = self._reopening_basis()
        if (
            not basis or self._state["busy"] or self._state["refreshing"]
            or self._state["uncertain_save"] or self._state["reviewing"]
            or self._state["reopening_review"]
        ):
            self._state["error"] = "election_reopening_not_ready"
            self.stateChanged.emit()
            return False
        reason = reason.strip()
        if not reason:
            self._state["error"] = "reason_required"
            self.stateChanged.emit()
            return False
        self._state.update(
            reopening_review={**basis, "reason": reason}, reopening_changed=False, error="",
        )
        self.stateChanged.emit()
        return True

    @Slot()
    def cancelReopening(self) -> None:
        if self._state["busy"] or self._state["uncertain_save"]:
            return
        if self._state["reopening_review"]:
            self._state.update(reopening_review={}, reopening_changed=False, error="")
            self.stateChanged.emit()

    @Slot(str, str)
    def reopen(self, reason: str, password: str) -> None:
        basis = self._reopening_basis()
        review = self._state["reopening_review"]
        self._observe_reopening_review()
        if (
            not basis or self._state["busy"] or self._state["refreshing"]
            or self._state["uncertain_save"] or self._state["reopening_changed"]
        ):
            self._state["error"] = (
                "election_completion_review_changed" if self._state["reopening_changed"]
                else "election_reopening_not_ready"
            )
            self.stateChanged.emit()
            return
        reviewed = review or {**basis, "reason": reason.strip()}
        if not reviewed["reason"] or not password:
            self._state["error"] = (
                "reason_required" if not reviewed["reason"] else "invalid_credentials"
            )
            self.stateChanged.emit()
            return
        payload = {
            "request_id": str(uuid4()),
            **{key: value for key, value in reviewed.items() if key != "election_id"},
        }
        self._save_election_command("reopenings", payload, password)

    def _save_election_command(
        self, action: str, payload: dict[str, Any], password: str,
    ) -> None:
        election_id = self._state["election_id"]
        path = f"/api/workspace/elections/{election_id}/{action}"
        command = {
            "namespace": "election", "election_id": election_id,
            "workflow": "election_completion", "method": "POST", "path": path,
            "actor_id": self._state["actor_id"], "request_id": payload["request_id"],
            "payload": deepcopy(payload),
        }
        self._command = command
        self._generation += 1
        generation = self._generation
        self._state.update(
            busy=True, error="", pending_request_id=payload["request_id"],
            review={}, reviewing=False, newer_basis=False,
            reopening_review={}, reopening_changed=False,
        )
        self.stateChanged.emit()

        def saved(body: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if not valid_operational_receipt(command, body):
                self._state.update(busy=False, uncertain_save=True, error="invalid_response")
                self.stateChanged.emit()
                return
            self._settled(body)

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            uncertain = code in NETWORK_ERRORS - {"recovery_journal_unavailable"}
            self._state.update(busy=False, uncertain_save=uncertain, error=code)
            if not uncertain:
                self._command = None
                self._state["pending_request_id"] = ""
            self.stateChanged.emit()

        self._request(path, "POST", {**payload, "password": password}, saved, failed)
