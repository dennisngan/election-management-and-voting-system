import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QByteArray, QEventLoop, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
    QSslCertificate,
    QSslConfiguration,
)

from election.desktop.translations import TRANSLATIONS

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
        }
        self._token = ""
        self._generation = 0
        self._refreshing = False
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

    def _tick(self) -> None:
        self._state["clock"] = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S HKT")
        self.stateChanged.emit()

    def _invalidate_pending_replies(self) -> None:
        self._generation += 1
        self._refreshing = False

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
        payload: dict[str, str] | None,
        success: ResultHandler,
        failure: Callable[[str], None],
        *,
        token: str = "",
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
        if method == "POST":
            reply = self._manager.post(request, QByteArray(json.dumps(payload).encode()))
        elif method == "DELETE":
            reply = self._manager.sendCustomRequest(request, QByteArray(b"DELETE"))
        else:
            reply = self._manager.get(request)
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
                try:
                    body = json.loads(bytes(reply.readAll().data())) if status != 204 else {}
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
            self.stateChanged.emit()

        self._request("/api/health", "GET", None, healthy, failed)

    def _clear_session(self) -> None:
        self._token = ""
        self._invalidate_pending_replies()
        self._state.update(
            phase="signed_out",
            account={},
            expires="—",
            busy=False,
            election=None,
            constituency=None,
            station=None,
        )
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
