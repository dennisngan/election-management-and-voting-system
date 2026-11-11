# Prepare and present the demo

The demo importer creates a fictional election through the application's HTTPS API, including
four staff accounts, station assignments, reviewed polling records and counting prerequisites.
Run the commands below from the repository root. Install Docker with Compose, start Docker,
and install the project's Python environment with `uv sync --locked` first.

## Start a separate demo server

```sh
uv run --locked python scripts/prepare_demo.py start --stage polling
```

The first build can take several minutes. This creates a separate Compose project on
`https://localhost:8444`. Its generated files live under the ignored `.runtime/demo/` directory:

| File | Purpose |
| --- | --- |
| `config.yml` | Separate server configuration |
| `ca.pem` | Public certificate authority for the desktop client |
| `ACCOUNTS.md` | Private presenter sheet with the four usernames and generated passwords |
| `state.json` | Private credentials and progress needed to resume the import |
| `mysql/` | Demo database files |

Keep this directory and its Docker volumes together. `ACCOUNTS.md`, `state.json` and
`config.yml` contain credentials; do not include them in shared slides or source packages.
First-login password changes and station assignments are already completed by the importer.

| Username | Demonstration role |
| --- | --- |
| `demo_admin` | Election setup and staff accounts |
| `demo_polling` | Polling records, complaints and queue observations |
| `demo_counting` | Accounting and count entry |
| `demo_supervisor` | Review, approval and finalization |

Use the Supervisor's generated password when an approval asks for password confirmation.

## Open the desktop client

For a source checkout on macOS/Linux:

```sh
export PYTHONPATH="$PWD/src"
uv run --locked python -m election.desktop --server https://localhost:8444 --ca .runtime/demo/ca.pem
```

In Windows PowerShell:

```powershell
$env:PYTHONPATH = "$PWD\src"
uv run --locked python -m election.desktop --server https://localhost:8444 --ca .runtime/demo/ca.pem
```

For an existing native Windows client, pass the same server address and the full path to
`ca.pem` to `Election Desk.exe`, as described in [Windows setup](../docs/WINDOWS-SETUP.md).
Sign in using the private account sheet and select the Harbour Community Hall station.

## Advance through the demonstration

| Stage | Prepared records |
| --- | --- |
| `polling` | Active election, approved opening, received stock, allocations, remaining-stock snapshot, approved turnout, zero special-paper observation, an open complaint and a queue observation |
| `counting` | Polling closure approved, P(18) accounting approved, local ballot box received, counting scope prepared and a complete draft count |
| `results` | Count approved and selected, election finalized, results exported |

Advance after saving any desktop edits:

```sh
uv run --locked python scripts/prepare_demo.py start --stage counting
```

```sh
uv run --locked python scripts/prepare_demo.py start --stage results
```

After a transition, sign out and back in to reload the updated context. The results stage writes
`demo-results.csv` and `demo-results.pdf` under `.runtime/demo/`.

You may start directly at `counting` or `results` to prepare everything up to that stage.
Stages advance only. Repeating the same command resumes preparation using the saved progress;
it does not reset records or undo changes made during the presentation. There is no reset command.
For a fresh rehearsal, use another directory and port:

```sh
uv run --locked python scripts/prepare_demo.py start --directory .runtime/demo-rehearsal --port 8446 --stage polling
```

Use that same directory and port in subsequent rehearsal commands and connect the client to
`https://localhost:8446` with `.runtime/demo-rehearsal/ca.pem`.

To stop the original demo while retaining it:

```sh
docker compose -f .runtime/demo/config.yml stop
```

Restart by repeating its `start` command with its current stage. Preserve `state.json`; starting
with fresh local progress against a database already containing the demo is refused.

## What the sample data means

The source is [scenario.json](scenario.json): one constituency, two candidates, one station that
counts locally, two issuance counters and one ballot box. Names are fictional.

| Quantity | Value |
| --- | --- |
| Received papers | 520: ordinary 500, replacement reserve 10, tendered reserve 10 |
| Allocated to counters | 200 each, 400 total |
| Remaining at counters | 50 each, 100 total |
| Ordinary stock held centrally | 100 |
| Ordinary papers issued / supplied turnout | 300 / 300 |
| Replacement, tendered and retrieved papers | Zero |
| Candidate votes | Alex Chan 170, Jamie Wong 125 |
| Invalid papers | 5 |
| Counted papers | 170 + 125 + 5 = 300 |

The fixed stock arithmetic keeps accounting and counting consistent. Scenario v1 expects these
stock ranges and two counters. If you edit the scenario, use a new demo directory; an existing
import refuses a changed scenario file.

The default election date is yesterday in Asia/Hong_Kong, with planned polling from 08:00 to
09:00 and prepared milestones through 09:30. Historical event times allow preparation without
waiting for a future schedule. The queue reminder is therefore stale by design. For a live
queue-entry demonstration, use the same election date at 08:58, after the seeded 08:55 observation;
the reminder remains stale because the event is historical. Do this before the results stage,
when finalization makes operational records read-only.

## Ten-minute presenter runbook

| Time | Action |
| --- | --- |
| 0–2 minutes | Sign in as `demo_admin`; show election, candidates, station and staff assignments. |
| 2–4 minutes | Sign in as `demo_polling`; show stock and turnout, then add the historical queue observation or complete the prepared complaint. |
| 4–5 minutes | Run `start --stage counting`; sign in as `demo_counting`; show prepared accounting and the ballot box. |
| 5–7 minutes | Show the complete draft count and explain 170 + 125 + 5 = 300. |
| 7–9 minutes | Run `start --stage results`; sign in as `demo_supervisor`; show approved results and preserved history. |
| 9–10 minutes | Open the exported PDF or CSV and explain the selected result. |

The stage commands perform the recorded reviews and approvals during preparation. If you plan
to click approvals manually on stage, rehearse that sequence separately and stop the importer
at the preceding stage.

## Import into an existing empty demo server

Use this alternative only for a separate server with no elections, or to resume this import's
own dataset. Existing unrelated elections are refused. Obtain that server's public CA first:

```sh
uv run --locked python scripts/prepare_demo.py import --server https://localhost:8443 --ca ca.pem --admin admin --stage polling
```

The command prompts privately for the Administrator password and, if required, its first-login
password change. It creates the four demo accounts without resetting existing accounts. Progress
and the presenter sheet are saved in `.runtime/demo-import/`. Advance with the same command and
connection details, changing only `--stage` to `counting` or `results`. On interruption, rerun the
same command with the same directory and public CA.

## Linux server with import from your Mac

Use a dedicated demo deployment. The importer refuses unrelated elections. Update the Linux
server's source checkout to include the new demo files, and use an updated checkout on your Mac.
Linux needs Docker with Compose; run the importer on your Mac over trusted HTTPS, so no host
Python installation is needed on Linux.

The default `config.example.yml` has one uncommented account, `admin`. First startup creates
all accounts listed under `x-election.accounts`, only if the database has no accounts. The
importer then adds `demo_admin`, `demo_polling`, `demo_counting` and `demo_supervisor` without
replacing the original Administrator: **five accounts with the default configuration**.

On Linux, from the repository root:

```sh
cp config.example.yml config.yml
```

Edit `x-election.server.host` to the DNS name or IP your Mac will use, and `server.bind` to the
server's actual private LAN/VPN interface. Preserve the YAML anchors, including `&server_bind`
and `&mysql_data`. Choose a fresh demo database directory and replace the initial Administrator's
placeholder password. The example below uses `192.168.1.50`; replace it with your server's address
and ensure your Mac can reach HTTPS port 8443.

```sh
docker compose -f config.yml up -d --build
```

```sh
docker compose -f config.yml cp api:/run/election/tls/ca.pem ./ca.pem
```

On your Mac, from the updated repository root, copy only the public CA. Replace the SSH username
and remote repository path:

```sh
scp demo-user@192.168.1.50:/path/to/election-system/ca.pem ./linux-server-ca.pem
```

```sh
uv sync --locked
```

```sh
uv run --locked python scripts/prepare_demo.py import --server https://192.168.1.50:8443 --ca linux-server-ca.pem --admin admin --directory .runtime/linux-demo --stage polling
```

Enter the original Administrator's password when prompted; its first-login password change is
also prompted if still required. This import generates new passwords for the Linux server's demo
accounts; use its account sheet rather than passwords from your local demo. The election data
is saved in the Linux server's database. The private account sheet and import state are saved
on the machine running the importer: `.runtime/linux-demo/ACCOUNTS.md` and
`.runtime/linux-demo/state.json` on your Mac. Connect the desktop client to the same server URL
using `linux-server-ca.pem`, and sign in with the generated demo accounts.

To advance, reuse exactly the same connection arguments and `--directory .runtime/linux-demo`,
changing `--stage polling` to `--stage counting` and later `--stage results`. Keep the directory
for retries and subsequent stages; it records the import's credentials and progress.
