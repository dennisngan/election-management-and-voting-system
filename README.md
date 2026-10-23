# Election Management and Voting System

A staff application for physical-ballot election operations, using a Python FastAPI server,
MySQL 8.4/InnoDB, and a PySide6 Qt Quick desktop client. The selected interface is **Material
workspace**. The approved scope and ordered tickets are in [the specification](docs/SPECIFICATION.md)
and [ticket plan](docs/TICKET-PLAN.md).

Ticket 01 establishes real-server sign-in, first-password change, revocable sessions, and the desktop
workspace shell. Ticket 02 adds Administrator draft elections, single-seat constituencies and
independent candidate lists, with three-language forms, replay-safe creates and revision conflicts.
Ticket 03 adds scoped polling stations, issuance counters and same-constituency counting destinations.
Tickets 04 and 05 add staff administration, assigned-station workspaces, election schedules and
single-election activation; their current verification status is recorded in the local tickets.
Ticket 06 adds revision-bound opening/closing records and Supervisor approval. Ticket 07 adds
received-stock pools, retained corrections and translated receipt statements. Independent slices
also implement normal turnout, complaint cases/statistics, queue observations and box handover.
Tickets 01–06 are complete. Tickets 07, 11, 13, 14 and 15 retain pending native Computer checks;
remaining stock-flow/counting/delivery work follows the dependency plan. Illustrative
design-preview figures are not application data.

After signing in as an Administrator and changing the initial password, open **Election setup**.
Create or choose a saved election, then create or choose a constituency and its candidates. Saved
lists refresh from the server while local form entries stay intact. A conflicting save preserves
your entries; use **Reload saved data** to review the latest version before editing again. Reloading
or changing a selection asks before discarding an affected unsaved form. Each constituency has one
seat and one choice per valid ballot. Candidate numbers are unique within their own constituency.

Open **Station setup** to choose an election and constituency, create polling stations, and add each
station's issuance counters. A station counts locally or sends to a local-counting station in the same
constituency. A receiving station with configured senders cannot be redirected until those senders
are reassigned. Station codes are unique within their constituency; counter codes within their station.

Open **Staff accounts** to create an individual account with a temporary password, choose its role
and permitted stations, edit or disable it, or reset its password. Administrative account changes
revoke that account's existing sessions. A reset requires a password change at its next sign-in.
The last enabled Administrator cannot be disabled or demoted. Polling Officers, Counting Officers
and Supervisors see their assigned station contexts; Administrator access alone grants no operational
approval authority. Passwords are cleared from the forms and excluded from audit history.

Open **Election schedule** to enter an election date, opening and closing date/time in Hong Kong time,
and a reporting interval from 1 to 1,440 minutes. Closing may fall on the following day. Save the
schedule before confirming activation. Activation requires a candidate and a station in every
constituency, with a counter in every station. The backend atomically permits one active election;
the desktop labels it separately from the selected draft. Active configuration is read-only, while
other drafts remain available. A planned time does not itself open or close a station.

An assigned Polling Officer opens **Polling operations** to save and submit actual opening,
closure to new arrivals, queue-clear forecasts and actual completion of queued service separately.
A Supervisor reviews the submitted revision in their own account and reconfirms their current
password. Corrections create new drafts with a reason and retain earlier approvals and history.

Open **Received stock and reserves** to record a ballot series and inclusive printed serial ranges
in separate ordinary, replacement and tendered pools. Enter all three starting quantities,
including zero reserves. Saved receipts can be corrected with an explanation; historical revisions
remain read-only. Select a saved revision to preview or export its statement as PDF or UTF-8 CSV
in the selected language. PDFs use the [bundled Chinese font](docs/report-font.md). Characters that
the PDF renderer cannot represent produce a visible export error; preview and CSV retain the
source text. The server serializes PDF builds around the shared font's subsetting state.

Open **Normal-mode turnout** to enter supplied hourly/cumulative figures and their external source
for a configured reporting period. An explicit zero is a saved report; a missing period stays missing.
A Supervisor confirms the exact submitted revision using their own existing password. Approved
totals use compatible consecutive periods from a zero starting baseline. Earlier amendments
retain the original approvals and flag affected later periods for renewed review. Choose the
reviewed revision or current station overview before previewing/exporting P(15).

Open **Complaint categories** as an Administrator to configure three-language display labels and
availability. Verified reference labels remain separate from project translations/custom labels;
Other remains available and requires a description. Assigned officers use **Complaint cases** to
record receipt, category, progress/completion and reasoned corrections. Older case revisions retain
their category labels and references. Cases outside the schedule remain explicitly identified.

Open **P(19) complaint period statistics** to prepare period statistics from saved cases, including
an explicit zero. The received cohort and work status are frozen when the revision is prepared.
Submit the reviewed revision for Supervisor confirmation. Late case entries and corrections can
make that basis stale; use reasoned amendments and renewed review while earlier counts, members
and approvals remain available. Report selection distinguishes the reviewed revision from the
current station overview. Complaint recording and zero reporting do not require an opening event.

Open **Queue waiting times** to record a waiting-time band or explicitly confirm the same band,
retaining the observation time and history. The shared reminder uses the latest actual observation and the
30-minute update boundary. Open **Box handover and milestones** to prepare sealed boxes at their
origin, record departure where applicable, and acknowledge receipt at the configured counting
destination. Local boxes still require receipt. Counting Officers record conversion completion,
first-box opening and the start of questionable-paper determination. Count completion remains
unrecorded until the later counting workflow supplies it. Translated PDF/CSV statements retain
origin, destination, event corrections and exact source references.

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
`UV_PROJECT_ENVIRONMENT=.venv-server uv sync --group server --group reports`; a source desktop environment can
use a separate `.venv-desktop` with `--only-group desktop`. Packaged clients do not need server packages.

## Local database and HTTPS

The local helpers prepare a development MySQL instance and local TLS material:

```sh
uv run --all-groups --locked python -m election.manage mysql-dev
uv run --all-groups --locked python -m election.manage tls-dev
```

The database helper creates the `election-system-mysql` container, binds it to
`127.0.0.1:13307`, and retains its data in a named Docker volume. It generates private credentials in
`.runtime/mysql.env` and connection settings in `.env`. It provisions two separate test databases:
`election_test` under `ELECTION_TEST_DATABASE_URL`, and `election_lifecycle_test` under
`ELECTION_LIFECYCLE_TEST_DATABASE_URL`. It refuses to overwrite an existing `.env` on first setup.
Repeated use starts the existing development container and ensures both test databases and grants
exist. For older project-generated settings, it appends the missing lifecycle URL without replacing
any existing values. Custom settings must supply that URL explicitly; the helper will not guess a
different server or credentials. No account has a fixed default password.

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

Integration tests require dedicated real MySQL databases configured through
`ELECTION_TEST_DATABASE_URL` and `ELECTION_LIFECYCLE_TEST_DATABASE_URL`. The local `mysql-dev` command
above provisions both. For a separate MySQL service, create and grant access to distinct test databases
and set both URLs in private `.env` or environment variables. The ordinary test database name must end
in `_test`; the lifecycle database name must end in `_lifecycle_test`.

Lifecycle API and desktop checks use their own database because they change the single active-election
pointer and reset synthetic activation state between cases. They must not share the development
database or the ordinary test database. Follow the test configuration rather than pointing tests at
operational data. API checks prove persisted authentication/session behavior; native GUI checks and screenshots
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
