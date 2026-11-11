"""Small trusted-HTTPS client and private, resumable demo import journal."""

import json
import os
import ssl
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid5


class DemoError(Exception):
    """An actionable error whose text contains no credentials."""


def private_write(path: Path, content: str | bytes) -> None:
    """Replace private generated files atomically; never follow an output symlink."""
    if path.is_symlink() or path.parent.is_symlink():
        raise DemoError("Demo output paths must not be symbolic links.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.is_symlink():
        raise DemoError("Demo temporary output must not be a symbolic link.")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(content.encode("utf-8") if isinstance(content, str) else content)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    if os.name == "posix":
        path.chmod(0o600)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise DemoError("The server redirected the request; use its direct HTTPS address.")


class DemoAPI:
    def __init__(self, server: str, ca: Path, state_path: Path, state: dict[str, Any]) -> None:
        parsed = urlsplit(server)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise DemoError("Use a direct HTTPS server address, such as https://localhost:8444.")
        self.server = server.rstrip("/")
        self.state_path, self.state = state_path, state
        self.opener = build_opener(
            ProxyHandler({}),
            HTTPSHandler(context=ssl.create_default_context(cafile=str(ca))),
            NoRedirect(),
        )
        self.token = ""
        self.password = ""
        self.clients: dict[str, DemoRole] = {}

    def save(self) -> None:
        private_write(self.state_path, json.dumps(self.state, ensure_ascii=False, indent=2) + "\n")

    def key(self, label: str) -> str:
        return str(uuid5(UUID(self.state["import_id"]), label))

    def _request(self, method: str, path: str, data: dict[str, Any] | None, token: str) -> bytes:
        if not path.startswith("/api/") or path.startswith("//"):
            raise DemoError("Demo requests must stay within this server's /api/ endpoints.")
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        payload = None
        if data is not None:
            payload = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.server + path, data=payload, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=45) as response:
                content: bytes = response.read()
                return content
        except HTTPError as error:
            try:
                detail = json.loads(error.read()).get("detail", {})
                code = (
                    detail.get("code", "request_failed")
                    if isinstance(detail, dict)
                    else "request_failed"
                )
                fields = detail.get("fields", []) if isinstance(detail, dict) else []
            except ValueError, AttributeError:
                code, fields = "request_failed", []
            raise DemoError(
                f"{method} {path}: HTTP {error.code}, {code}, fields={fields}"
            ) from None
        except URLError, TimeoutError, OSError:
            raise DemoError(
                f"{method} {path}: connection or certificate check failed. Check service status "
                "and the public CA, then rerun the same command with the same private state."
            ) from None

    def request(self, method: str, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = self._request(method, path, data, self.token)
        result: dict[str, Any] = json.loads(raw) if raw else {}
        return result

    def step(self, label: str, method: str, path: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._step(label, method, path, data, self)

    def _step(
        self, label: str, method: str, path: str, data: dict[str, Any], actor: Any
    ) -> dict[str, Any]:
        steps = self.state.setdefault("steps", {})
        if label not in steps:
            pending = self.state.setdefault("pending_steps", {})
            pending[label] = {"method": method, "path": path, "request_id": data.get("request_id")}
            self.save()
            response = actor.request(method, path, data)
            steps[label] = response
            pending.pop(label, None)
            self.save()
            print("  Prepared: " + label, flush=True)
        result: dict[str, Any] = steps[label]
        return result

    def login(self, username: str, password: str) -> dict[str, Any]:
        result = self.request(
            "POST", "/api/auth/login", {"username": username, "password": password}
        )
        self.token, self.password = result["token"], password
        account: dict[str, Any] = result["account"]
        return account

    def as_role(self, role: str) -> DemoRole:
        if role not in self.clients:
            account = self.state["accounts"][role]
            result = self.request(
                "POST",
                "/api/auth/login",
                {"username": account["username"], "password": account["password"]},
            )
            self.clients[role] = DemoRole(self, result["token"], account["password"])
        return self.clients[role]

    def close(self) -> None:
        actors: list[DemoAPI | DemoRole] = [*self.clients.values(), self]
        for actor in actors:
            if actor.token:
                try:
                    actor.request("DELETE", "/api/auth/session")
                except DemoError:
                    pass
                actor.token = ""


class DemoRole:
    def __init__(self, root: DemoAPI, token: str, password: str) -> None:
        self.root, self.token, self.password = root, token, password

    def request(self, method: str, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = self.root._request(method, path, data, self.token)
        result: dict[str, Any] = json.loads(raw) if raw else {}
        return result

    def step(self, label: str, method: str, path: str, data: dict[str, Any]) -> dict[str, Any]:
        return self.root._step(label, method, path, data, self)

    def download(self, path: str, destination: Path) -> None:
        private_write(destination, self.root._request("GET", path, None, self.token))
