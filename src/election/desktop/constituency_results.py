"""Supervisor result review, tie resolution, and localized statement downloads."""

import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Property, QObject, Signal, Slot

from election.desktop.configuration import AuthorizedRequest
from election.desktop.event_times import format_event_time
from election.desktop.exact_numbers import qt_state, quantity_display
from election.desktop.report_files import DownloadRequest, report_destination, save_report

NETWORK_ERRORS = frozenset({"request_failed", "disconnected", "database_unavailable"})


class ConstituencyResultsController(QObject):
    stateChanged = Signal()

    def __init__(
        self,
        request: AuthorizedRequest,
        parent: QObject | None = None,
        *,
        download: DownloadRequest | None = None,
    ) -> None:
        super().__init__(parent)
        self._request = request
        self._download = download
        self._generation = self._report_generation = 0
        self._opened = False
        self._pending: tuple[str, str] | None = None
        self._state: dict[str, Any] = {}
        self.reset()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return qt_state(quantity_display(self._state))

    def reset(self) -> None:
        self._generation += 1
        self._report_generation += 1
        self._opened = False
        self._pending = None
        self._state = {
            "context": {},
            "constituency_id": 0,
            "role": "",
            "result": {},
            "busy": False,
            "refreshing": False,
            "error": "",
            "notice": "",
            "selected_candidate_id": 0,
            "reason": "",
            "dirty": False,
            "newer_basis": False,
            "uncertain_save": False,
            "report": {},
            "report_text": "",
            "export_path": "",
        }
        self.stateChanged.emit()

    def set_context(self, context: dict[str, Any]) -> None:
        constituency = context.get("constituency") or {}
        account = context.get("account") or {}
        constituency_id = constituency.get("id", 0)
        role = account.get("role", "")
        account_id = account.get("id", 0)
        changed = (
            constituency_id != self._state["constituency_id"]
            or role != self._state["role"]
            or account_id != self._state.get("account_id", 0)
        )
        opened = self._opened
        if changed:
            self.reset()
            self._opened = opened
        self._state.update(
            context=deepcopy(context),
            constituency_id=constituency_id if type(constituency_id) is int else 0,
            role=role,
            account_id=account_id if type(account_id) is int else 0,
        )
        self.stateChanged.emit()
        if changed and self._opened and self._state["constituency_id"]:
            self.reload()

    def _path(self, suffix: str = "") -> str:
        return f"/api/workspace/constituencies/{self._state['constituency_id']}/results{suffix}"

    def _error(self, code: str) -> None:
        self._state.update(error=code, notice="")
        self.stateChanged.emit()

    def _clear_report(self) -> None:
        self._report_generation += 1
        self._state.update(report={}, report_text="", export_path="")

    @staticmethod
    def _tie_revision(result: dict[str, Any]) -> int:
        resolution = result.get("tie_resolution")
        revision = resolution.get("revision", 0) if isinstance(resolution, dict) else 0
        return revision if type(revision) is int else 0

    @staticmethod
    def _valid_result(body: Any, constituency_id: int) -> bool:
        if not isinstance(body, dict):
            return False
        context = body.get("context")
        if not isinstance(context, dict) or not isinstance(context.get("constituency"), dict):
            return False
        if context["constituency"].get("id") != constituency_id:
            return False
        if type(body.get("complete")) is not bool or type(body.get("provisional")) is not bool:
            return False
        if not isinstance(body.get("candidate_totals"), list):
            return False
        if not isinstance(body.get("contributions"), list) or not isinstance(
            body.get("pending"), list
        ):
            return False
        if not isinstance(body.get("leader_candidate_ids"), list):
            return False
        if not isinstance(body.get("tie_candidate_ids"), list):
            return False
        if not isinstance(body.get("basis_digest"), str):
            return False
        return all(
            isinstance(row, dict)
            and type(row.get("candidate_id")) is int
            and (row.get("quantity") is None or type(row.get("quantity")) is int)
            for row in body["candidate_totals"]
        )

    def _load(self, *, background: bool) -> None:
        constituency_id = self._state["constituency_id"]
        if not constituency_id:
            self._error("constituency_not_selected")
            return
        if self._state["role"] != "supervisor":
            self._error("supervisor_required")
            return
        if self._state["busy"]:
            return
        self._generation += 1
        if not background:
            self._state["refreshing"] = False
        generation = self._generation
        activity = "refreshing" if background else "busy"
        preserve_review_error = bool(
            (self._state["dirty"] or self._state["uncertain_save"]) and self._state["error"]
        )
        self._state.update(
            **{activity: True},
            error=self._state["error"] if preserve_review_error else "",
            notice="",
        )
        self.stateChanged.emit()

        def loaded(body: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            self._state[activity] = False
            if not self._valid_result(body, constituency_id):
                self._state.update(error="request_failed", notice="")
                self.stateChanged.emit()
                return
            old = self._state["result"]
            if self._state["dirty"] or self._state["uncertain_save"]:
                changed = bool(
                    old
                    and (
                        old.get("basis_digest") != body.get("basis_digest")
                        or self._tie_revision(old) != self._tie_revision(body)
                    )
                )
                if changed:
                    self._state["newer_basis"] = True
                    self._state["notice"] = "constituency_result_newer_basis"
            else:
                self._state.update(result=deepcopy(body), newer_basis=False)
                self._clear_report()
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            self._state[activity] = False
            if background and preserve_review_error:
                self.stateChanged.emit()
                return
            self._state.update(error=code, notice="")
            self.stateChanged.emit()

        self._request(self._path(), "GET", None, loaded, failed)

    @Slot()
    def open(self) -> None:
        self._opened = True
        if not self._state["result"]:
            self.reload()

    @Slot()
    def reload(self) -> None:
        if self._state["dirty"] or self._state["uncertain_save"]:
            self.refresh()
            return
        self._load(background=False)

    @Slot()
    def refresh(self) -> None:
        if (
            not self._opened
            or not self._state["constituency_id"]
            or self._state["role"] != "supervisor"
            or self._state["busy"]
            or self._state["refreshing"]
        ):
            return
        self._load(background=True)

    @Slot(str, result=str)
    def formatTime(self, value: str) -> str:
        return format_event_time(value)

    def _can_review(self) -> bool:
        result = self._state["result"]
        context = result.get("context", {})
        election = context.get("election", {}) if isinstance(context, dict) else {}
        return bool(
            self._state["role"] == "supervisor"
            and result.get("complete") is True
            and len(result.get("tie_candidate_ids", [])) >= 2
            and election.get("status") == "active"
            and not self._state["newer_basis"]
            and not self._state["busy"]
        )

    @Slot(int)
    def setResolutionCandidate(self, candidate_id: int) -> None:
        if self._state["uncertain_save"]:
            self._error("unsaved_tie_resolution")
            return
        result = self._state["result"]
        if not self._can_review() or candidate_id not in result.get("tie_candidate_ids", []):
            self._error("tie_candidate_invalid")
            return
        self._state.update(
            selected_candidate_id=candidate_id,
            dirty=True,
            error="",
            notice="",
        )
        self._pending = None
        self._clear_report()
        self.stateChanged.emit()

    @Slot(str)
    def setResolutionReason(self, reason: str) -> None:
        if self._state["uncertain_save"]:
            self._error("unsaved_tie_resolution")
            return
        if not self._can_review():
            self._error("constituency_result_read_only")
            return
        if len(reason) > 2000:
            self._error("tie_resolution_reason_required")
            return
        self._state.update(
            reason=reason,
            dirty=bool(self._state["selected_candidate_id"] or reason.strip()),
            error="",
            notice="",
        )
        self._pending = None
        self._clear_report()
        self.stateChanged.emit()

    @Slot()
    def discardAndReload(self) -> None:
        if self._state["busy"]:
            return
        if self._state["uncertain_save"]:
            self._error("unsaved_tie_resolution")
            return
        self._pending = None
        self._state.update(
            selected_candidate_id=0,
            reason="",
            dirty=False,
            newer_basis=False,
            error="",
            notice="",
        )
        self._clear_report()
        self.stateChanged.emit()
        self.reload()

    @Slot(str)
    def resolveTie(self, password: str) -> None:
        if self._state["busy"]:
            return
        if not password:
            self._error("invalid_credentials")
            return
        retrying_uncertain = self._state["uncertain_save"]
        result = self._state["result"]
        if retrying_uncertain:
            if self._state["role"] != "supervisor" or self._pending is None:
                self._error("unsaved_tie_resolution")
                return
            try:
                pending_command = json.loads(self._pending[0])
                path = pending_command["path"]
                body = pending_command["body"]
            except TypeError, ValueError, KeyError:
                self._error("unsaved_tie_resolution")
                return
            if (
                path != self._path("/tie-resolutions")
                or type(body.get("candidate_id")) is not int
                or not isinstance(body.get("reason"), str)
                or not body["reason"].strip()
                or not isinstance(body.get("basis_digest"), str)
            ):
                self._error("unsaved_tie_resolution")
                return
            candidate_id = body["candidate_id"]
            reason = body["reason"]
            command = {**body, "request_id": self._pending[1], "password": password}
        else:
            if not self._can_review():
                self._error("constituency_result_read_only")
                return
            candidate_id = self._state["selected_candidate_id"]
            reason = self._state["reason"]
            if candidate_id not in result.get("tie_candidate_ids", []):
                self._error("tie_candidate_invalid")
                return
            if not reason.strip() or len(reason) > 2000:
                self._error("tie_resolution_reason_required")
                return
            resolution = result.get("tie_resolution")
            expected_revision = resolution.get("revision", 0) if isinstance(resolution, dict) else 0
            body = {
                "expected_resolution_revision": expected_revision,
                "basis_digest": result["basis_digest"],
                "candidate_id": candidate_id,
                "reason": reason,
            }
            signature = json.dumps(
                {"path": self._path("/tie-resolutions"), "body": body},
                sort_keys=True,
                ensure_ascii=False,
            )
            if self._pending is None or self._pending[0] != signature:
                self._pending = signature, str(uuid4())
            command = {**body, "request_id": self._pending[1], "password": password}
        self._generation += 1
        generation = self._generation
        self._state.update(busy=True, refreshing=False, error="", notice="", uncertain_save=False)
        self.stateChanged.emit()

        def saved(body: dict[str, Any]) -> None:
            if generation != self._generation:
                return
            if not self._valid_result(body, self._state["constituency_id"]):
                self._state.update(busy=False, error="request_failed", uncertain_save=True)
                self.stateChanged.emit()
                return
            resolution_view = body.get("tie_resolution")
            if not (
                body.get("basis_digest") == result.get("basis_digest")
                and body.get("resolved_candidate_id") == candidate_id
                and isinstance(resolution_view, dict)
                and resolution_view.get("reason") == reason
                and resolution_view.get("valid") is True
            ):
                self._state.update(busy=False, error="request_failed", uncertain_save=True)
                self.stateChanged.emit()
                return
            self._pending = None
            self._state.update(
                busy=False,
                result=deepcopy(body),
                selected_candidate_id=0,
                reason="",
                dirty=False,
                newer_basis=False,
                uncertain_save=False,
                error="",
                notice="constituency_tie_resolved",
            )
            self._clear_report()
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation != self._generation:
                return
            uncertain = code in NETWORK_ERRORS or (
                retrying_uncertain and code == "invalid_credentials"
            )
            self._state.update(busy=False, error=code, notice="", uncertain_save=uncertain)
            if code in ("constituency_result_basis_stale", "tie_resolution_revision_conflict"):
                self._state["newer_basis"] = True
                uncertain = False
                self._state["uncertain_save"] = False
            if not uncertain:
                self._pending = None
            self.stateChanged.emit()

        self._request(self._path("/tie-resolutions"), "POST", command, saved, failed)

    @staticmethod
    def _preview_text(body: dict[str, Any]) -> str:
        rows = body.get("rows", [])
        return "\n".join(
            " · ".join(str(value) for value in row) for row in rows if isinstance(row, list)
        )

    def _report_path(self, locale: str, extension: str = "") -> str | None:
        if locale not in ("tc", "sc", "en") or not self._state["constituency_id"]:
            self._error("constituency_result_not_found")
            return None
        if self._state["dirty"] or self._state["uncertain_save"] or self._state["newer_basis"]:
            self._error(
                "constituency_result_newer_basis"
                if self._state["newer_basis"]
                else "unsaved_tie_resolution"
            )
            return None
        return self._path("/statement" + extension) + f"?locale={locale}"

    @Slot(str)
    def preview(self, locale: str) -> None:
        path = self._report_path(locale)
        if path is None or self._state["busy"]:
            return
        constituency_id = self._state["constituency_id"]
        result_digest = self._state["result"].get("basis_digest")
        self._clear_report()
        generation = self._report_generation
        self._generation += 1
        self._state["refreshing"] = False
        request_generation = self._generation
        self._state.update(busy=True, error="", notice="")
        self.stateChanged.emit()

        def loaded(body: dict[str, Any]) -> None:
            if request_generation != self._generation or generation != self._report_generation:
                return
            report_result = body.get("result")
            if not (
                body.get("locale") == locale
                and isinstance(report_result, dict)
                and report_result.get("context", {}).get("constituency", {}).get("id")
                == constituency_id
                and report_result.get("basis_digest") == result_digest
                and isinstance(body.get("tables"), list)
            ):
                self._state.update(busy=False, error="request_failed", notice="")
                self.stateChanged.emit()
                return
            self._state.update(
                busy=False,
                report=deepcopy(body),
                report_text=self._preview_text(body),
                error="",
                notice="constituency_result_report_ready",
            )
            self.stateChanged.emit()

        def failed(code: str) -> None:
            if request_generation == self._generation and generation == self._report_generation:
                self._state.update(busy=False, error=code, notice="")
                self.stateChanged.emit()

        self._request(path, "GET", None, loaded, failed)

    @Slot(str, str, str)
    def exportReport(self, locale: str, format: str, filepath: str) -> None:
        if format not in ("pdf", "csv") or self._download is None:
            self._error("constituency_result_export_failed")
            return
        destination = report_destination(filepath)
        path = self._report_path(locale, "." + format)
        if path is None:
            return
        if destination is None:
            self._error("constituency_result_export_failed")
            return
        if self._state["busy"]:
            return
        self._generation += 1
        generation = self._generation
        report_generation = self._report_generation
        self._state.update(busy=True, refreshing=False, error="", notice="", export_path="")
        self.stateChanged.emit()

        def failed(code: str) -> None:
            if generation == self._generation and report_generation == self._report_generation:
                self._state.update(busy=False, error=code, notice="")
                self.stateChanged.emit()

        def loaded(body: dict[str, Any]) -> None:
            if generation != self._generation or report_generation != self._report_generation:
                return
            if not save_report(body, destination, format):
                failed("constituency_result_export_failed")
                return
            self._state.update(
                busy=False,
                export_path=destination,
                notice="constituency_result_exported",
                error="",
            )
            self.stateChanged.emit()

        self._download(path, loaded, failed)
