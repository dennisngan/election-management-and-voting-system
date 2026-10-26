import json
import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    Property,
    QByteArray,
    QEventLoop,
    QObject,
    QStandardPaths,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
    QSslCertificate,
    QSslConfiguration,
)

from election.desktop.accounting import AccountingController
from election.desktop.allocations import AllocationController
from election.desktop.boxes import BoxesController
from election.desktop.client_command_journal import CommandJournal, JournalError, command_workflow
from election.desktop.complaint_categories import ComplaintCategoriesController
from election.desktop.complaint_periods import ComplaintPeriodsController
from election.desktop.complaints import ComplaintCasesController
from election.desktop.configuration import ConfigurationController
from election.desktop.counter_returns import CounterReturnsController
from election.desktop.counting_rounds import CountingRoundsController
from election.desktop.counting_scopes import CountingScopesController
from election.desktop.fallback import FallbackController
from election.desktop.invalid_reasons import InvalidReasonsController
from election.desktop.lifecycle import LifecycleController
from election.desktop.operational_receipts import valid_operational_receipt
from election.desktop.outages import OutagesController
from election.desktop.polling import PollingController
from election.desktop.queue import QueueController
from election.desktop.recovery import RecoveryController
from election.desktop.special_papers import SpecialPapersController
from election.desktop.staff import StaffController
from election.desktop.stock import StockController
from election.desktop.stock_snapshots import StockSnapshotsController
from election.desktop.translations import TRANSLATIONS
from election.desktop.turnout import TurnoutController
from election.desktop.workspace import WorkspaceController

HKT = timezone(timedelta(hours=8), "HKT")
ResultHandler = Callable[[dict[str, Any]], None]


class DesktopController(QObject):
    stateChanged = Signal()
    eraseSecrets = Signal()

    def __init__(self, server_url: str = "https://localhost:8443", ca_file: str = "") -> None:
        super().__init__()
        self._state: dict[str, Any] = {
            "phase": "signed_out",
            "locale": "tc",
            "server_url": server_url,
            "connection": "pending",
            "busy": False,
            "error": "",
            "notice": "",
            "last_refresh": "—",
            "clock": "",
            "account": {},
            "expires": "—",
            "election": None,
            "constituency": None,
            "station": None,
            "active_election": None,
            "capabilities": {},
        }
        self._token = ""
        journal_directory = os.environ.get("ELECTION_CLIENT_STATE_DIR") or str(
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppLocalDataLocation
                )
            )
            / "operational-commands"
        )
        self._command_journal = CommandJournal(Path(journal_directory))
        self._recovery = RecoveryController(self._authorized_request, self._command_journal, self)
        self._outages = OutagesController(self._authorized_request, self)
        self._configuration = ConfigurationController(self._authorized_request, self)
        self._lifecycle = LifecycleController(self._authorized_request, self)
        self._lifecycle.stateChanged.connect(self._lifecycle_changed)
        self._staff = StaffController(self._authorized_request, self)
        self._complaint_categories = ComplaintCategoriesController(self._authorized_request, self)
        self._invalid_reasons = InvalidReasonsController(self._authorized_request, self)
        self._staff.accessChanged.connect(self._access_changed)
        self._polling = PollingController(self._authorized_request, self)
        self._stock = StockController(self._authorized_request, self._authorized_download, self)
        self._allocations = AllocationController(
            self._authorized_request, self._authorized_download, self
        )
        self._stock_snapshots = StockSnapshotsController(
            self._authorized_request, self, download=self._authorized_download
        )
        self._special_papers = SpecialPapersController(
            self._authorized_request, self, download=self._authorized_download
        )
        self._counter_returns = CounterReturnsController(self._authorized_request, self)
        self._queue = QueueController(
            self._authorized_request, self, download=self._authorized_download
        )
        self._boxes = BoxesController(
            self._authorized_request, self, download=self._authorized_download
        )
        self._counting_scopes = CountingScopesController(
            self._authorized_request, self, download=self._authorized_download
        )
        self._counting_rounds = CountingRoundsController(
            self._authorized_request, self, download=self._authorized_download
        )
        self._accounting = AccountingController(
            self._authorized_request, self, download=self._authorized_download
        )
        self._fallback = FallbackController(self._authorized_request, self)
        self._turnout = TurnoutController(
            self._authorized_request, self, download=self._authorized_download
        )
        self._complaints = ComplaintCasesController(self._authorized_request, self)
        self._complaint_periods = ComplaintPeriodsController(
            self._authorized_request, self, download=self._authorized_download
        )
        self._workspace = WorkspaceController(
            self._authorized_request,
            self,
            selection_guard=lambda: bool(
                self._outages.property("state")["dirty"]
                or self._outages.property("state")["busy"]
                or self._accounting.property("state")["dirty"]
                or self._accounting.property("state")["busy"]
                or self._polling.property("state")["dirty"]
                or self._polling.property("state")["busy"]
                or self._stock.property("state")["dirty"]
                or self._stock.property("state")["busy"]
                or self._allocations.property("state")["dirty"]
                or self._allocations.property("state")["busy"]
                or self._stock_snapshots.property("state")["dirty"]
                or self._stock_snapshots.property("state")["busy"]
                or self._special_papers.property("state")["dirty"]
                or self._special_papers.property("state")["busy"]
                or self._counter_returns.property("state")["dirty"]
                or self._counter_returns.property("state")["busy"]
                or self._queue.property("state")["dirty"]
                or self._queue.property("state")["busy"]
                or self._boxes.property("state")["dirty"]
                or self._boxes.property("state")["busy"]
                or self._counting_scopes.property("state")["dirty"]
                or self._counting_scopes.property("state")["busy"]
                or self._counting_rounds.property("state")["dirty"]
                or self._counting_rounds.property("state")["busy"]
                or self._fallback.property("state")["dirty"]
                or self._fallback.property("state")["busy"]
                or self._turnout.property("state")["dirty"]
                or self._turnout.property("state")["busy"]
                or self._complaints.property("state")["dirty"]
                or self._complaints.property("state")["busy"]
                or self._complaint_periods.property("state")["dirty"]
                or self._complaint_periods.property("state")["busy"]
            ),
        )
        self._accounting.stateChanged.connect(self._workspace.stateChanged.emit)
        self._polling.stateChanged.connect(self._workspace.stateChanged.emit)
        self._stock.stateChanged.connect(self._workspace.stateChanged.emit)
        self._allocations.stateChanged.connect(self._workspace.stateChanged.emit)
        self._stock_snapshots.stateChanged.connect(self._workspace.stateChanged.emit)
        self._special_papers.stateChanged.connect(self._workspace.stateChanged.emit)
        self._counter_returns.stateChanged.connect(self._workspace.stateChanged.emit)
        self._queue.stateChanged.connect(self._workspace.stateChanged.emit)
        self._boxes.stateChanged.connect(self._workspace.stateChanged.emit)
        self._counting_scopes.stateChanged.connect(self._workspace.stateChanged.emit)
        self._counting_rounds.stateChanged.connect(self._workspace.stateChanged.emit)
        self._outages.stateChanged.connect(self._workspace.stateChanged.emit)
        self._fallback.stateChanged.connect(self._workspace.stateChanged.emit)
        self._turnout.stateChanged.connect(self._workspace.stateChanged.emit)
        self._complaints.stateChanged.connect(self._workspace.stateChanged.emit)
        self._complaint_periods.stateChanged.connect(self._workspace.stateChanged.emit)
        self._workspace.contextChanged.connect(self._workspace_changed)
        self._generation = 0
        self._refreshing = False
        self._active_refreshing = False
        self._active_generation = 0
        self._last_lifecycle_active: dict[str, Any] | None = None
        self._manager = QNetworkAccessManager(self)
        self._ssl = QSslConfiguration.defaultConfiguration()
        if ca_file:
            certificates = QSslCertificate.fromPath(str(Path(ca_file).resolve()))
            if not certificates:
                raise ValueError("The configured CA file contains no readable certificates")
            self._ssl.setCaCertificates(self._ssl.caCertificates() + certificates)
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick)
        self._clock_timer.start()
        self._tick()

    @Property(dict, notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return self._state.copy()

    @Property(dict, notify=stateChanged)
    def texts(self) -> dict[str, str]:
        return TRANSLATIONS[self._state["locale"]]

    @Property(QObject, constant=True)
    def configuration(self) -> ConfigurationController:
        return self._configuration

    @Property(QObject, constant=True)
    def lifecycle(self) -> LifecycleController:
        return self._lifecycle

    @Property(QObject, constant=True)
    def staff(self) -> StaffController:
        return self._staff

    @Property(QObject, constant=True)
    def complaintCategories(self) -> ComplaintCategoriesController:
        return self._complaint_categories

    @Property(QObject, constant=True)
    def invalidReasons(self) -> InvalidReasonsController:
        return self._invalid_reasons

    @Property(QObject, constant=True)
    def workspace(self) -> WorkspaceController:
        return self._workspace

    @Property(QObject, constant=True)
    def polling(self) -> PollingController:
        return self._polling

    @Property(QObject, constant=True)
    def stock(self) -> StockController:
        return self._stock

    @Property(QObject, constant=True)
    def allocations(self) -> AllocationController:
        return self._allocations

    @Property(QObject, constant=True)
    def stockSnapshots(self) -> StockSnapshotsController:
        return self._stock_snapshots

    @Property(QObject, constant=True)
    def specialPapers(self) -> SpecialPapersController:
        return self._special_papers

    @Property(QObject, constant=True)
    def counterReturns(self) -> CounterReturnsController:
        return self._counter_returns

    @Property(QObject, constant=True)
    def queue(self) -> QueueController:
        return self._queue

    @Property(QObject, constant=True)
    def boxes(self) -> BoxesController:
        return self._boxes

    @Property(QObject, constant=True)
    def countingScopes(self) -> CountingScopesController:
        return self._counting_scopes

    @Property(QObject, constant=True)
    def outages(self) -> OutagesController:
        return self._outages

    @Property(QObject, constant=True)
    def recovery(self) -> RecoveryController:
        return self._recovery

    @Property(QObject, constant=True)
    def countingRounds(self) -> CountingRoundsController:
        return self._counting_rounds

    @Property(QObject, constant=True)
    def fallback(self) -> FallbackController:
        return self._fallback

    @Property(QObject, constant=True)
    def turnout(self) -> TurnoutController:
        return self._turnout

    @Property(QObject, constant=True)
    def complaints(self) -> ComplaintCasesController:
        return self._complaints

    @Property(QObject, constant=True)
    def complaintPeriods(self) -> ComplaintPeriodsController:
        return self._complaint_periods

    @Property(QObject, constant=True)
    def accounting(self) -> AccountingController:
        return self._accounting

    def _workspace_changed(self) -> None:
        context = self._workspace.property("state")["selected"]
        self._recovery.set_context(
            context.get("station", {}).get("id", 0),
            self._state["account"].get("role", ""),
            self._state["server_url"],
            self._state["account"].get("id", 0),
        )
        self._outages.set_context(context)
        self._accounting.set_context(context)
        self._polling.set_context(context)
        self._stock.set_context(context)
        self._allocations.set_context(context)
        self._stock_snapshots.set_context(context)
        self._special_papers.set_context(context)
        self._counter_returns.set_context(context)
        self._queue.set_context(context)
        self._boxes.set_context(context)
        self._counting_scopes.set_context(context)
        self._counting_rounds.set_context(context)
        self._fallback.set_context(context)
        self._turnout.set_context(context)
        self._complaints.set_context(context)
        self._complaint_periods.set_context(context)
        self._state["election"] = context.get("election") or self._state["active_election"]
        self._state["constituency"] = context.get("constituency")
        self._state["station"] = context.get("station")
        self._state["capabilities"] = context.get("capabilities", {})
        self.stateChanged.emit()

    def _apply_active_election(self, election: dict[str, Any] | None) -> None:
        self._state["active_election"] = election
        if not self._workspace.property("state")["selected"]:
            self._state["election"] = election
        self._configuration.sync_active_election(election)
        self.stateChanged.emit()

    def _lifecycle_changed(self) -> None:
        if self._state["phase"] == "workspace":
            election = self._lifecycle.property("state").get("active_election")
            if isinstance(election, dict) and election != self._last_lifecycle_active:
                self._last_lifecycle_active = election
                self._active_generation += 1
                self._apply_active_election(election)

    def _refresh_active_election(self) -> None:
        if self._active_refreshing or self._state["phase"] != "workspace":
            return
        self._active_refreshing = True
        generation = self._active_generation

        def loaded(data: dict[str, Any]) -> None:
            self._active_refreshing = False
            if generation != self._active_generation:
                return
            election = data.get("election")
            if election is not None and (
                not isinstance(election, dict) or type(election.get("id")) is not int
            ):
                self._error("request_failed")
                return
            self._apply_active_election(election)

        def failed(code: str) -> None:
            self._active_refreshing = False
            if generation != self._active_generation:
                return
            self._error(code)

        self._authorized_request("/api/active-election", "GET", None, loaded, failed)

    def _access_changed(self) -> None:
        self._clear_session()
        self._state.update(error="access_changed", notice="")
        self.stateChanged.emit()

    def _authorized_request(
        self,
        path: str,
        method: str,
        payload: dict[str, Any] | None,
        success: ResultHandler,
        failure: Callable[[str], None],
    ) -> None:
        command = None
        workflow = command_workflow(path)
        account_id = self._state["account"].get("id", 0)
        origin = self._state["server_url"]
        if workflow and payload and method in ("POST", "PUT", "PATCH") and "request_id" in payload:
            try:
                command = self._command_journal.prepare(
                    origin, account_id, workflow[0], workflow[1], path, method, payload
                )
            except (OSError, ValueError, KeyError, TypeError, JournalError) as error:
                failure(
                    str(error)
                    if isinstance(error, JournalError)
                    else "recovery_journal_unavailable"
                )
                return

        def remember(status: str, *, body: dict[str, Any] | None = None, code: str = "") -> None:
            if command is not None:
                self._command_journal.record_outcome(
                    origin, account_id, command["request_id"], status, record=body, error=code
                )

        def saved(body: dict[str, Any]) -> None:
            if command is not None:
                valid = valid_operational_receipt(command, body)
                try:
                    remember(
                        "committed" if valid else "uncertain",
                        body=body,
                        code="" if valid else "invalid_response",
                    )
                except OSError, ValueError, RuntimeError:
                    failure("recovery_journal_unavailable")
                    return
                if not valid:
                    failure("request_failed")
                    return
            success(body)

        def failed(code: str) -> None:
            try:
                remember(
                    "uncertain"
                    if code
                    in {
                        "disconnected",
                        "request_failed",
                        "invalid_response",
                        "certificate_error",
                        "database_unavailable",
                        "session_expired",
                        "access_changed",
                    }
                    or (command is not None and command["status"] == "uncertain"
                        and not command.get("retry_after_not_found"))
                    or code == "invalid_credentials" and command is not None
                    and command["status"] == "uncertain"
                    else "rejected",
                    code=code,
                )
            except OSError, ValueError, RuntimeError:
                code = "recovery_journal_unavailable"
            failure(code)
            if code == "session_expired":
                self._error(code)

        self._request(path, method, payload, saved, failed, token=self._token)

    def _authorized_download(
        self, path: str, success: ResultHandler, failure: Callable[[str], None]
    ) -> None:
        def failed(code: str) -> None:
            failure(code)
            if code == "session_expired":
                self._error(code)

        self._request(path, "GET", None, success, failed, token=self._token, binary=True)

    def _configuration_access(self) -> None:
        account = self._state["account"]
        administrator = (
            self._state["phase"] == "workspace"
            and account.get("role") == "administrator"
            and not account.get("must_change_password", True)
        )
        self._configuration.set_available(administrator)
        self._lifecycle.set_available(administrator)
        account_id = account.get("id", 0)
        self._staff.set_available(administrator, account_id if type(account_id) is int else 0)
        self._complaint_categories.set_available(administrator)
        self._invalid_reasons.set_available(administrator)
        self._workspace.set_available(
            self._state["phase"] == "workspace"
            and not account.get("must_change_password", True)
            and account.get("role") in ("polling_officer", "counting_officer", "supervisor")
        )

    def _tick(self) -> None:
        self._state["clock"] = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S HKT")
        self.stateChanged.emit()

    def _invalidate_pending_replies(self) -> None:
        self._generation += 1
        self._refreshing = False
        self._active_refreshing = False

    @Slot(str)
    def setLocale(self, locale: str) -> None:
        if locale in TRANSLATIONS:
            self._state["locale"] = locale
            self.stateChanged.emit()

    @Slot(str, result=bool)
    def configureServer(self, server_url: str) -> bool:
        candidate = QUrl(server_url.strip())
        valid = (
            candidate.isValid()
            and candidate.scheme() == "https"
            and bool(candidate.host())
            and not candidate.userInfo()
            and not candidate.hasQuery()
            and not candidate.hasFragment()
            and candidate.path() in ("", "/")
        )
        if not valid:
            self._state["error"] = "invalid_server"
            self.stateChanged.emit()
            return False
        normalized = candidate.toString().rstrip("/")
        if normalized != self._state["server_url"]:
            if self._token:
                self._state["error"] = "request_failed"
                self.stateChanged.emit()
                return False
            self._invalidate_pending_replies()
            self._state["server_url"] = normalized
            self._state["connection"] = "pending"
            self._state["last_refresh"] = "—"
            self._state["error"] = ""
        self.stateChanged.emit()
        return True

    def _request(
        self,
        path: str,
        method: str,
        payload: dict[str, Any] | None,
        success: ResultHandler,
        failure: Callable[[str], None],
        *,
        token: str = "",
        binary: bool = False,
    ) -> QNetworkReply:
        request = QNetworkRequest(QUrl(self._state["server_url"] + path))
        request.setSslConfiguration(self._ssl)
        request.setTransferTimeout(8000)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        if token:
            request.setRawHeader(
                QByteArray(b"Authorization"), QByteArray(b"Bearer " + token.encode())
            )
        # Send credentials on a fresh connection after an idle server close.
        # Background reads retain their existing manager and active replies.
        credential_request = (
            method == "POST"
            and payload is not None
            and not {
                "password",
                "current_password",
                "new_password",
                "temporary_password",
            }.isdisjoint(payload)
        )
        credential_manager = QNetworkAccessManager(self) if credential_request else None
        manager = credential_manager if credential_manager is not None else self._manager
        if method == "POST":
            reply = manager.post(request, QByteArray(json.dumps(payload).encode()))
        elif method == "PUT":
            reply = manager.put(request, QByteArray(json.dumps(payload).encode()))
        elif method == "DELETE":
            reply = manager.sendCustomRequest(request, QByteArray(b"DELETE"))
        else:
            reply = manager.get(request)
        generation = self._generation
        ssl_failed = False

        def ssl_error(errors: object) -> None:
            nonlocal ssl_failed
            ssl_failed = True

        reply.sslErrors.connect(ssl_error)

        def finished() -> None:
            try:
                if generation != self._generation:
                    return
                status = int(
                    reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
                )
                if 200 <= status < 300 and reply.error() != QNetworkReply.NetworkError.NoError:
                    failure("certificate_error" if ssl_failed else "disconnected")
                    return
                raw = bytes(reply.readAll().data())
                if binary and 200 <= status < 300:
                    success(
                        {
                            "data": raw,
                            "content_type": str(
                                reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or ""
                            ),
                        }
                    )
                    return
                try:
                    body = json.loads(raw) if status != 204 else {}
                except json.JSONDecodeError, UnicodeDecodeError:
                    body = {}
                if 200 <= status < 300 and isinstance(body, dict):
                    success(body)
                else:
                    detail = body.get("detail", {}) if isinstance(body, dict) else {}
                    code = detail.get("code") if isinstance(detail, dict) else None
                    if ssl_failed:
                        code = "certificate_error"
                    elif status == 0:
                        code = "disconnected"
                    failure(
                        code
                        if isinstance(code, str) and code in TRANSLATIONS[self._state["locale"]]
                        else "request_failed"
                    )
            finally:
                reply.deleteLater()
                if credential_manager is not None:
                    credential_manager.deleteLater()

        reply.finished.connect(finished)
        return reply

    def _error(self, code: str) -> None:
        self._state["busy"] = False
        self._state["error"] = code
        if code in ("disconnected", "certificate_error", "database_unavailable"):
            self._state["connection"] = code
        if code == "session_expired":
            self._clear_session()
        self.stateChanged.emit()

    def _accept_session(self, data: dict[str, Any]) -> None:
        token, account = data.get("token"), data.get("account")
        try:
            expires = datetime.fromisoformat(data["expires_at"])
        except KeyError, TypeError, ValueError:
            self._error("request_failed")
            return
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(account, dict)
            or not all(
                isinstance(account.get(key), str) for key in ("username", "display_name", "role")
            )
            or type(account.get("must_change_password")) is not bool
            or expires.tzinfo is None
        ):
            self._error("request_failed")
            return
        self._invalidate_pending_replies()
        self._token = token
        self._state["account"] = account
        self._state["expires"] = expires.astimezone(HKT).strftime("%Y-%m-%d %H:%M HKT")
        self._state["phase"] = "password_change" if account["must_change_password"] else "workspace"
        self._state["busy"] = False
        self._state["error"] = ""
        self._state["connection"] = "connected"
        self._configuration_access()
        self.stateChanged.emit()
        self.refresh()

    @Slot(str, str, str)
    def signIn(self, server_url: str, username: str, password: str) -> None:
        if self._state["busy"] or not self.configureServer(server_url):
            return
        if not username.strip() or not password:
            self._error("validation_error")
            return
        self._state.update(busy=True, error="", notice="")
        self.stateChanged.emit()
        self._request(
            "/api/auth/login",
            "POST",
            {"username": username.strip(), "password": password},
            self._accept_session,
            self._error,
        )
        self.eraseSecrets.emit()

    @Slot(str, str, str)
    def changePassword(self, current: str, password: str, confirmation: str) -> None:
        if self._state["busy"] or not self._token:
            return
        if password != confirmation:
            self._error("password_mismatch")
            return
        if not current or not 12 <= len(password) <= 128:
            self._error("min_password")
            return
        self._invalidate_pending_replies()
        self._state.update(busy=True, error="", notice="")
        self.stateChanged.emit()

        def changed(data: dict[str, Any]) -> None:
            self._state["notice"] = "password_change_success"
            self._accept_session(data)

        self._request(
            "/api/auth/password",
            "POST",
            {"current_password": current, "new_password": password},
            changed,
            self._error,
            token=self._token,
        )
        self.eraseSecrets.emit()

    @Slot()
    def refresh(self) -> None:
        if self._refreshing or self._state["busy"]:
            return
        if not self.configureServer(self._state["server_url"]):
            return
        self._refreshing = True

        def failed(code: str) -> None:
            self._refreshing = False
            self._state["connection"] = code
            self.stateChanged.emit()

        def healthy(data: dict[str, Any]) -> None:
            self._state["connection"] = "connected"
            self._state["last_refresh"] = datetime.now(HKT).strftime("%H:%M:%S HKT")
            self._refreshing = False
            self.stateChanged.emit()
            if self._token:
                self._request("/api/auth/me", "GET", None, profile, self._error, token=self._token)

        def profile(data: dict[str, Any]) -> None:
            self._state["account"] = data
            self._configuration_access()
            self._configuration.refresh()
            self._lifecycle.refresh()
            self._staff.refresh()
            self._complaint_categories.refresh()
            self._invalid_reasons.refresh()
            self._workspace.refresh()
            self._accounting.refresh()
            self._polling.refresh()
            self._stock.refresh()
            self._allocations.refresh()
            self._stock_snapshots.refresh()
            self._special_papers.refresh()
            self._counter_returns.refresh()
            self._queue.refresh()
            self._boxes.refresh()
            self._counting_scopes.refresh()
            self._counting_rounds.refresh()
            self._outages.refresh()
            self._fallback.refresh()
            self._turnout.refresh()
            self._complaints.refresh()
            self._complaint_periods.refresh()
            self._refresh_active_election()
            self.stateChanged.emit()

        self._request("/api/health", "GET", None, healthy, failed)

    def _clear_session(self) -> None:
        self._token = ""
        self._last_lifecycle_active = None
        self._invalidate_pending_replies()
        self._state.update(
            phase="signed_out",
            account={},
            expires="—",
            busy=False,
            election=None,
            constituency=None,
            station=None,
            active_election=None,
            capabilities={},
        )
        self._configuration.reset()
        self._lifecycle.reset()
        self._staff.reset()
        self._complaint_categories.reset()
        self._invalid_reasons.reset()
        self._workspace.reset()
        self._accounting.reset()
        self._polling.reset()
        self._stock.reset()
        self._allocations.reset()
        self._stock_snapshots.reset()
        self._special_papers.reset()
        self._counter_returns.reset()
        self._queue.reset()
        self._boxes.reset()
        self._counting_scopes.reset()
        self._counting_rounds.reset()
        self._outages.reset()
        self._fallback.reset()
        self._turnout.reset()
        self._complaints.reset()
        self._complaint_periods.reset()
        self.eraseSecrets.emit()

    @Slot()
    def signOut(self) -> None:
        token = self._token
        self._clear_session()
        self._state.update(error="", notice="signed_out")
        if token:
            self._request(
                "/api/auth/session",
                "DELETE",
                None,
                lambda data: None,
                lambda code: None,
                token=token,
            )
        self.stateChanged.emit()

    @Slot()
    def shutdown(self) -> None:
        self._timer.stop()
        self._clock_timer.stop()
        if self._token:
            token = self._token
            self._clear_session()
            loop = QEventLoop()
            self._request(
                "/api/auth/session",
                "DELETE",
                None,
                lambda data: loop.quit(),
                lambda code: loop.quit(),
                token=token,
            )
            QTimer.singleShot(500, loop.quit)
            loop.exec()
