# Election Management and Voting System

A staff application for physical-ballot election operations, using a Python FastAPI server,
MySQL 8.4/InnoDB, and a PySide6 Qt Quick desktop client. The selected interface is **Material
workspace**. The approved scope and ordered tickets are in [the specification](docs/SPECIFICATION.md)
and [ticket plan](docs/TICKET-PLAN.md).

For a new server, use the [Docker quickstart](docs/QUICKSTART.md): copy `config.example.yml` to
`config.yml`, edit its settings and account list, then run `docker compose -f config.yml up -d --build`.
Docker Desktop uses Linux containers on Windows or macOS; Linux hosts use Docker Engine/Compose.

[Quickstart verification](docs/evidence/docker-deployment/QUICKSTART-VERIFICATION.md) at `733d28ac`:
**1,708 passed, 2 skipped, 27 warnings**, plus both separate real Docker journeys; Ruff, mypy and
both review axes pass. Actual Windows execution and native-client verification remain incomplete.

The implementation covers election/station/staff configuration, approved polling events, separate
ballot-stock pools and counter ownership, stock snapshots and turnout, EPR fallback, complaints and
queues, box handover, P(18)/F1–F4, selected approved counts, local and constituency recounts, outage
reconciliation and protected backup/restore. Election completion adds an immutable reviewed outcome;
authorized reopening retains that earlier outcome while later work receives new revisions and approval.

**25 of 27 tickets are formally complete: 01–23, 25 and 26. Ticket 24 is in progress; Ticket 27 delivery
is outstanding.** Current Ticket 24 focused results are not a replacement for the required final full
suite, matching packaged-client journeys, protected current-source restore or final Main integration.
[Delivery traceability](docs/DELIVERY-TRACEABILITY.md) records those gates and their actual source/build
scope. [Docker quickstart](docs/QUICKSTART.md) covers the central server;
[Windows setup](docs/WINDOWS-SETUP.md) covers native client builds and installation.

The earlier advanced Docker deployment and Windows ZIP tooling have [previous-source verification evidence](docs/evidence/docker-deployment/README.md):
**1,676 passed, 1 skipped, 35 warnings** at `d9453ceb`, plus the separate real Docker/Qt/PDF/CSV
journey and database-container replacement check. Ruff, mypy and both review axes passed for that
source. Those results predate the `config.yml` quickstart and do not verify its changes. Actual
Windows build/smoke and the broader final delivery gates below remain incomplete.

Follow the [synthetic demo runbook](docs/DEMO-RUNBOOK.md) for a reproducible manual example and the
[source/evidence delivery guide](docs/DELIVERY-PACKAGE.md) for allowlists, manifests and package checks.

The latest accepted historical batch passed **1,547 tests with 36 warnings** at
`edaff3020bd6c66aec1ead64c72cd66bb5ad59e9`, followed by Ruff and mypy. Its
[sealed evidence archive](docs/evidence/integrated/ticket22-23-25-final-edaff/README.md) includes the
representative protected restores and packaged readbacks for Tickets 22, 23 and 25. That source
predates Ticket 24; the result is not a current-source full-suite claim. Earlier ticket evidence and
failed/UNKNOWN runtime records retain their original identities and qualifications.

Actual Windows 11 x64 build/smoke, Windows private-file permissions, 125%/150% display scaling and
physical-printer checks remain **INCOMPLETE** until exercised on the required environment. macOS
validation does not satisfy them. Video production remains deferred. Illustrative design-preview
figures are not application data.

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

Open **Unissued counter stock returns** to record ordinary papers returned from a named
counter to the PRO, with their ballot series, printed serial range and original event time.
Only papers still held as unissued stock can be returned. Saved corrections require a reason
and preserve previous revisions; returned papers become available for later allocations.
These stock movements are separate from papers retrieved after issuance to an elector.

Open **P(12) Counter balances** to record all counters at one observation time. Check each
counter that has reported, then enter its remaining ordinary serial ranges. A checked counter
with no ranges explicitly reports zero; an unchecked counter is unreported and leaves the
observation incomplete. The server derives ordinary issuance from net allocations less remaining
stock, retaining the receipt, allocation and return revisions used for that observation.
Use a new observation for a later stock check, or a reasoned amendment to correct a saved one.
Select a saved or historical revision to preview/export its frozen P(12) statement in the chosen
language. Stock-derived issuance does not change supplied normal-mode turnout or verify electors.

Open **P(15) period turnout** to enter supplied hourly/cumulative figures and their external source
for a configured reporting period. An explicit zero is a saved report; a missing period stays missing.
A Supervisor confirms the exact submitted revision using their own existing password. Approved
totals use compatible consecutive periods from a zero starting baseline. Earlier amendments
retain the original approvals and flag affected later periods for renewed review. Choose the
reviewed revision or current station overview before previewing/exporting P(15).

Open **EPR fallback** to record an external-register interruption while the management app remains
connected. Record the original time, confirmed external cumulative baseline, and the current complete
P(12) snapshot at that exact time. A Supervisor confirms the source before fallback becomes active.
Select fallback sources in P(15); cumulative turnout uses the confirmed baseline plus subsequent
ordinary issuance. Replacement and tendered reserves do not add ordinary voters.

Record recovery against the original activation and an exact-time complete P(12) source. The app
retains the stock-derived total, recovered external total and their difference. Supervisor confirmation
returns to normal mode; affected P(15) approvals require a reasoned amendment and renewed review.
A recovered 116 replaces an estimated 115. Reasoned source corrections retain earlier revisions;
P(15) previews and PDF/CSV exports retain their selected sources and interval coverage. Counting
Officers can inspect these records but cannot prepare or approve polling-station turnout.

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

## Deploy the central service

Install Docker with Compose, then run these commands from the repository folder. On macOS/Linux:

```sh
cp config.example.yml config.yml
```

On Windows, use PowerShell with Docker Desktop set to Linux containers:

```powershell
Copy-Item config.example.yml config.yml
```

Edit only the `x-election` settings at the top of `config.yml`: the server hostname, bind address,
port, MySQL data directory and initial account list. Replace every example password with a unique
temporary password of 12–128 characters and include an Administrator. Then start the server:

```sh
docker compose -f config.yml up -d --build
```

The same Compose command works in PowerShell, macOS Terminal and a Linux terminal. No host Python,
MySQL, WSL terminal, setup script or environment profile is needed. Docker prepares HTTPS and a
fresh independent database, waits for MySQL, initializes the schema and creates the configured
accounts together. The first sign-in requires a password change. Existing accounts are preserved
on restart; editing the list does not add, reset, change or disable accounts after bootstrap.

The default `localhost`/`127.0.0.1` settings accept clients on the server computer. Choose a stable
reachable hostname/IP and private bind address before first startup for other computers. MySQL data
defaults to `./data/mysql`; private keys, generated secrets and backups use persistent Docker volumes.
Keep the new deployment separate from old development databases and retained datasets.

Follow the [quickstart](docs/QUICKSTART.md) to export the public CA, connect a desktop client and
retain state on stop/restart. Startup refuses an incompatible existing schema; the quickstart also
documents explicit schema maintenance. The [advanced deployment guide](docs/DOCKER-DEPLOYMENT.md) retains the
separate `compose.yaml`/shell workflow and its maintenance procedures. Actual Windows verification
remains incomplete.

## Development prerequisites

- uv and Python 3.14.
- MySQL 8.4, or a running local Docker-compatible engine for the development database helper.
- A graphical desktop session for the native client. Windows 11, 64-bit is the delivery target;
  macOS development checks do not establish Windows compatibility.

From the repository root, install all development groups:

```sh
uv sync --locked --all-groups
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
`UV_PROJECT_ENVIRONMENT=.venv-server uv sync --locked --no-default-groups --group server --group reports`; a source desktop environment can
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

Use a separate prepared test environment and explicit dedicated MySQL fixture roles. Test setup
migrates and mutates those databases; it must never use operational or retained native datasets.
The local validation role mapping is:

| Variable | Reserved fixture schema | Purpose |
| --- | --- | --- |
| `ELECTION_TEST_DATABASE_URL` | `election_t17_fixture_test` | Ordinary mutable fixtures. |
| `ELECTION_LIFECYCLE_TEST_DATABASE_URL` | `election_t19_comparisons_lifecycle_test` | Lifecycle fixtures and backup source. |
| `ELECTION_RESTORE_DATABASE_URL` | `election_t17_reports_test` | Explicit disposable restore destination. |

Supply private MySQL URLs for these roles through the process environment. The restore URL is
required explicitly and must differ from both sources. `election_t19_workflow_edges_test` and
`election_t19_comparisons_test` are protected retained observers and are rejected as ordinary/restore
fixtures. Provision distinct test roles through the database owner's setup; a `_test` suffix alone
does not establish ownership. Preserve affected data privately before migration or maintenance,
reserve exclusive use, and retain failed/unknown results. Do not reset a retained dataset to run tests.

```sh
uv run --locked --all-groups --no-sync python -m ruff check src tests migrations scripts
uv run --locked --all-groups --no-sync python -m mypy src
uv run --locked --all-groups --no-sync python -m pytest
```

Lifecycle fixtures change the active-election pointer and synthetic activation state. Restore
fixtures replace only their explicitly reserved destination. Keep environments and test roles
separate from the operational installation. API checks prove persisted behavior; native GUI checks
and screenshots prove interaction. Export/import/process startup alone does not establish a complete
workflow. [Delivery traceability](docs/DELIVERY-TRACEABILITY.md) records source/build and pending gates.

Record the actual environment, commands, results, and GUI evidence for each ticket. Windows packaging
and the packaged-client smoke test remain separate delivery work. Actual Windows verification is
pending ticket 27; per-ticket evidence records the completed development checks.

## Native macOS validation

For Computer-driven validation on macOS, use the locked validation environment and a fresh
lowercase run name containing letters, digits and hyphens. Existing build outputs are retained.

```sh
uv run --locked --all-groups --no-sync python scripts/build_macos_validation.py --run-name native-demo-v1
".runtime/macos-package-native-demo-v1/dist/Election Desk.app/Contents/MacOS/Election Desk" \
  --server https://localhost:8443 --ca "$PWD/.runtime/tls/ca.pem"
```

Add `--peer` to build a separately identified second desktop process under
`.runtime/macos-package-native-demo-v1-peer/`. Its app is `Election Desk Peer.app`. All client
processes still use normal sign-in and the configured shared HTTPS backend. Keep each validation
client's command-state directory private and separate from retained earlier journeys.

The helper builds a macOS validation artifact. [Windows setup](docs/WINDOWS-SETUP.md) documents the
separate Windows builder and runtime folder; actual Windows checks remain INCOMPLETE.
`--window-size 910 512` sets a small logical window. `QT_SCALE_FACTOR=1.25` or `1.5` exercises Qt on
the current host and does not establish actual Windows display-scaling compatibility.

The isolated UI-test API runs with `uv run --all-groups --locked python tests/ui_server.py` on port
8444. It accepts only a database ending in `_test` and reads a controlled UTC clock and sign-in delay
from `.runtime/ui-check-settings.json`. This test fixture exercises the normal API routes and real
MySQL while making loading and 24-hour expiry observable. It is not the operational server.

Per-ticket results and Computer screenshots are recorded in [Ticket 01 evidence](docs/evidence/ticket-01/README.md).
