# Election Management and Voting System

**COMP 8500SEF — Software Engineering**

A course project based on **Topic 2: Election Management and Voting System**.

This desktop application supports election staff from election setup and polling-station
operations to ballot accounting, manual count recording, recounts, approvals and results reporting.
It records operational activities and aggregate figures; electors cast their votes on paper ballots.

Built with **Python 3.14**, **PySide6/Qt Quick**, **FastAPI** and **MySQL 8.4**. The repository includes
the application source, requirements specification, architecture decisions and fictional demo data.

## Run locally and load sample data

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and
[Docker Desktop](https://docs.docker.com/get-started/get-docker/), then start Docker Desktop
with Linux containers enabled.
Download and extract this repository, or clone it. Open PowerShell or a terminal in the project
folder and run these two commands in order:

```sh
uv run --locked python scripts/prepare_demo.py start
uv run --locked --directory src python -m election.desktop --server https://localhost:8444 --ca ../.runtime/demo/ca.pem
```

Wait for the first command to finish successfully before running the second. The first run needs
internet access and may take several minutes to download Python, dependencies and Docker images.

The first command starts the API and MySQL in Docker and imports the fictional election and
demo accounts automatically. No separate sample-data import is needed. The second opens the
desktop application using Python on your computer. The API is available only locally at
`https://localhost:8444`. Certificates are generated automatically; no configuration editing or
manual certificate installation is needed.

The sample data comes from [`demo/scenario.json`](demo/scenario.json), included in the repository.
On a fresh clone, the first command creates `.runtime/demo/` automatically for local database files,
certificates and generated passwords. You do not need to create or download this folder yourself;
it is intentionally excluded from Git.

### Sign in

Open **`.runtime/demo/ACCOUNTS.md`** in the project folder for the generated passwords.
Start with `demo_admin` to explore the election setup, or use an account below for its workflow:

| Username | Role |
| --- | --- |
| `demo_admin` | Election setup and staff management |
| `demo_polling` | Polling records, ballot stock, turnout and complaints |
| `demo_counting` | Ballot accounting and count entry |
| `demo_supervisor` | Review, approval and finalization |

The demo accounts are ready to use, with station assignments already configured. Select
**Harbour Community Hall** when asked for a station. The interface supports English,
Traditional Chinese and Simplified Chinese. Use the Supervisor's generated password when
confirming an approval.

The initial demo is prepared for polling. To explore counting and finalized results, follow the
[demo walkthrough](demo/README.md#advance-through-the-demonstration).

### Stop and resume

Close the desktop application, then stop the local server:

```sh
docker compose -f .runtime/demo/config.yml stop
```

The demo data is retained. Repeat the two startup commands to resume the polling demo. If you
advanced to counting or results, restart with that same stage as explained in the walkthrough.
Local demo files are stored under `.runtime/`, which is excluded from Git.

## Alternative: run the server with Python

For the simplest setup, use Docker for the API and database as shown above. The desktop already
runs with Python. To run the API without Docker as well, follow the
[manual Python setup](docs/PYTHON-SETUP.md). This requires a separately installed MySQL 8.4 server,
a fresh database and localhost HTTPS certificates, so it takes more setup.

## Main features

- Election, constituency, candidate, station and staff management.
- Ballot stock, turnout, complaints, queues and ballot-box handover.
- Ballot accounting, manual count recording, recounts, approvals and preserved result history.
- PDF and CSV reports in three languages.

## Further documentation

- [Demo data and presentation walkthrough](demo/README.md)
- [Requirements and project specification](docs/SPECIFICATION.md)
- [Server deployment for multiple computers](docs/QUICKSTART.md)
- [Windows client build and installation](docs/WINDOWS-SETUP.md)
- [Architecture and design decisions](docs/adr/) and [domain glossary](GLOSSARY.md)
