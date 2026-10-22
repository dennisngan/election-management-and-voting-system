"""Local Computer-test fixture: the real API/MySQL with controlled time and network delay.

Never use this fixture for operational data. Only a database ending in _test is accepted.
The ordinary application endpoints are unchanged; no test endpoint is added to the product.
"""

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from dotenv import dotenv_values
from fastapi import Request, Response
from sqlalchemy.engine import make_url

from election.server.app import create_app

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / ".runtime/ui-check-settings.json"


def fixture_time() -> datetime:
    return datetime.fromisoformat(json.loads(SETTINGS.read_text())["now"]).astimezone(UTC)


def main() -> None:
    url = os.getenv("ELECTION_TEST_DATABASE_URL") or dotenv_values(ROOT / ".env").get(
        "ELECTION_TEST_DATABASE_URL"
    )
    if not url or not (make_url(url).database or "").endswith("_test"):
        raise SystemExit("The UI fixture requires a dedicated MySQL database ending in _test")
    if not SETTINGS.exists():
        SETTINGS.parent.mkdir(exist_ok=True)
        SETTINGS.write_text(json.dumps({"now": datetime.now(UTC).isoformat(), "login_delay": 3}))
    app = create_app(url, now=fixture_time)

    @app.middleware("http")
    async def network_delay(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method == "POST" and request.url.path == "/api/auth/login":
            delay = float(json.loads(SETTINGS.read_text()).get("login_delay", 0))
            await asyncio.sleep(max(0, min(delay, 10)))
        return await call_next(request)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8444,
        loop="asyncio",
        ws="none",
        ssl_certfile=str(ROOT / ".runtime/tls/server.pem"),
        ssl_keyfile=str(ROOT / ".runtime/tls/server-key.pem"),
        access_log=False,
    )


if __name__ == "__main__":
    main()
