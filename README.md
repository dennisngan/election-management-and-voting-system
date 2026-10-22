# Election Management and Voting System

A staff application for physical-ballot election operations, using a Python FastAPI server,
MySQL 8.4/InnoDB, and a PySide6 Qt Quick desktop client. The selected interface is **Material
workspace**. The approved scope and sequential tickets are in [the specification](docs/SPECIFICATION.md)
and [ticket plan](docs/TICKET-PLAN.md).

Ticket 01 establishes real-server sign-in, first-password change, revocable sessions, and the desktop
workspace shell. Later polling, stock, reporting, and counting features are delivered by subsequent
tickets; illustrative design-preview figures are not application data.

## Development prerequisites

- uv and Python 3.14.
- MySQL 8.4, or a running local Docker-compatible engine for the development database helper.
- A graphical desktop session for the native client. Windows 11, 64-bit is the delivery target;
  macOS development checks do not establish Windows compatibility.

From the repository root, install all development groups:

```sh
uv sync --all-groups
```

The project does not install itself as a Python package. Set its source path before running commands.
On macOS/Linux:

```sh
export PYTHONPATH="$PWD/src"
```

On Windows PowerShell:

```powershell
$env:PYTHONPATH = "$PWD\src"
```

If the default uv cache is unavailable in a restricted environment, set `UV_CACHE_DIR` to a writable
directory before running uv. Server, desktop, reports, and development dependencies are separate
groups; `uv.lock` records the resolved versions.

Development commands below keep all groups available so starting the desktop does not remove the
running server's dependencies. For an isolated server environment, use
`UV_PROJECT_ENVIRONMENT=.venv-server uv sync --only-group server`; a source desktop environment can
use a separate `.venv-desktop` with `--only-group desktop`. Packaged clients do not need server packages.

## Local database and HTTPS

The local helpers prepare a development MySQL instance and local TLS material:

```sh
uv run --all-groups --locked python -m election.manage mysql-dev
uv run --all-groups --locked python -m election.manage tls-dev
```

The database helper creates the `election-system-mysql` container, binds it to
`127.0.0.1:13307`, and retains its data in a named Docker volume. It generates private credentials in
`.runtime/mysql.env` and connection settings in `.env`, including a separate `election_test` database
URL under `ELECTION_TEST_DATABASE_URL`. It refuses to overwrite an existing `.env` on first setup;
repeated use starts the existing development container. No account has a fixed default password.

Wait for the container's health status to become `healthy` before running migrations:

```sh
docker inspect --format '{{.State.Health.Status}}' election-system-mysql
```

The server reads `ELECTION_DATABASE_URL` from the environment or the private repository-root `.env`.
For an existing MySQL service, configure your own dedicated database and user instead, for example:

```dotenv
ELECTION_DATABASE_URL=mysql+pymysql://<database-user>:<URL-encoded-password>@127.0.0.1:13307/<database-name>?charset=utf8mb4
```

Keep `.env`, generated credentials, certificates, and private keys out of version control. The
database is MySQL throughout development and tests; SQLite is not a substitute.

The TLS helper generates `.runtime/tls/ca.pem`, `server.pem`, and `server-key.pem` for local development,
and refuses to replace existing TLS files. The server defaults to those server certificate/key paths;
custom paths use `ELECTION_TLS_CERT` and `ELECTION_TLS_KEY`. These certificates cover `localhost` and
`127.0.0.1`; deployment to other computers requires the appropriate server name and trusted certificate.

Run the schema migration and provision an initial individual account:

```sh
uv run --all-groups --locked python -m election.manage migrate
uv run --all-groups --locked python -m election.manage bootstrap --username local.admin --display-name "Local Administrator"
```

The bootstrap username/display name above are examples; choose the individual account to provision.
Bootstrap prompts twice for a temporary password using hidden input and requires 12–128 characters.
Do not put the password in command arguments, screenshots, or source files. The first sign-in requires
a password change.

No real voter records or voter identities are needed for the fixture. Tests use isolated synthetic
accounts and databases; the bootstrap account belongs only to the database you configure.

## Run the server and client

Start the HTTPS server in one terminal, with the source path and database configuration above:

```sh
uv run --all-groups --locked python -m election.server
```

Start the client in another terminal. For the local development certificate:

```sh
export PYTHONPATH="$PWD/src"
export ELECTION_SERVER_URL=https://localhost:8443
export ELECTION_CA_FILE=.runtime/tls/ca.pem
uv run --all-groups --locked python -m election.desktop
```

Windows PowerShell equivalent:

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:ELECTION_SERVER_URL = "https://localhost:8443"
$env:ELECTION_CA_FILE = ".runtime/tls/ca.pem"
uv run --all-groups --locked python -m election.desktop
```

The client uses the API and has no database credentials. Configure a reachable server address and
trusted certificate for separate computers on the private LAN/VPN. Certificate errors must be fixed
through the configured trust chain, not bypassed. Sessions have a 24-hour absolute lifetime with no
inactivity timeout; signing out or closing the client removes usable local session credentials.

The Ticket 01 API exposes health at `GET /api/health`, sign-in at `POST /api/auth/login`, profile at
`GET /api/auth/me`, password change at `POST /api/auth/password`, logout at
`DELETE /api/auth/session`, and the authorized workspace at `GET /api/workspace`.

## Verification

With development dependencies installed:

```sh
uv run --all-groups ruff check .
uv run --all-groups mypy src/election
uv run --all-groups pytest
```

Integration tests require their dedicated real MySQL database configured through
`ELECTION_TEST_DATABASE_URL`. Follow the test configuration rather than pointing tests at operational
data. API checks prove persisted authentication/session behavior; native GUI checks and screenshots
prove the desktop interaction. A successful export, import, or
process start alone does not prove the full workflow.

Record the actual environment, commands, results, and GUI evidence for each ticket. Windows packaging
and the packaged-client smoke test remain separate delivery work. Actual Windows verification is
pending ticket 27; per-ticket evidence records the completed development checks.

## Native macOS validation

For Computer-driven validation on macOS, build the local native launcher after installing all groups:

```sh
uv run --all-groups --locked python scripts/build_macos_validation.py
".runtime/native/Election Desk.app/Contents/MacOS/Election Desk" \
  --server https://localhost:8443 --ca "$PWD/.runtime/tls/ca.pem"
```

The launcher stays under ignored `.runtime/`. The helper is for development GUI validation; Windows
release packaging and actual Windows checks remain ticket 27. `--window-size 910 512` sets a small
logical window for layout checks. `QT_SCALE_FACTOR=1.25` or `1.5` exercises Qt scaling on the current
platform; it does not establish Windows display-scaling compatibility.

The isolated UI-test API runs with `uv run --all-groups --locked python tests/ui_server.py` on port
8444. It accepts only a database ending in `_test` and reads a controlled UTC clock and sign-in delay
from `.runtime/ui-check-settings.json`. This test fixture exercises the normal API routes and real
MySQL while making loading and 24-hour expiry observable. It is not the operational server.

Per-ticket results and Computer screenshots are recorded in [Ticket 01 evidence](docs/evidence/ticket-01/README.md).
