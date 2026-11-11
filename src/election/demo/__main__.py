"""Prepare a private, fictional election demo through the normal HTTPS API."""

import argparse
import getpass
import hashlib
import json
import os
import secrets
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from election.demo.client import DemoAPI, DemoError, private_write

ROOT = Path(__file__).resolve().parents[3]
HKT = timezone(timedelta(hours=8))
STAGES = ("polling", "counting", "results")
ROLES = {
    "administrator": ("demo_admin", "Demo Administrator"),
    "polling_officer": ("demo_polling", "Demo Polling Officer"),
    "counting_officer": ("demo_counting", "Demo Counting Officer"),
    "supervisor": ("demo_supervisor", "Demo Supervisor"),
}


def run_docker(config: Path, *arguments: str, capture: bool = False) -> str:
    try:
        completed = subprocess.run(
            ["docker", "compose", "-f", str(config), *arguments],
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
        )
    except OSError, subprocess.CalledProcessError:
        raise DemoError(
            "Docker Compose failed. Correct the reported error and rerun this command."
        ) from None
    return completed.stdout if capture else ""


def scenario_data(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data: dict[str, Any] = json.loads(raw)
    # This presentation uses a deliberately small, balanced two-counter example.
    expected_stock = {
        "series": "DEMO",
        "ordinary_from": "000001",
        "ordinary_to": "000500",
        "replacement_from": "000501",
        "replacement_to": "000510",
        "tendered_from": "000511",
        "tendered_to": "000520",
    }
    if (
        data.get("version") != 1
        or len(data.get("candidates", [])) != 2
        or len(data.get("counters", [])) != 2
        or data.get("stock") != expected_stock
        or data.get("turnout") != 300
        or len(data.get("votes", [])) != 2
        or any(
            type(value) is not int or value < 0 for value in [*data["votes"], data.get("invalid")]
        )
        or sum(data["votes"]) + data["invalid"] != 300
    ):
        raise DemoError(
            "Scenario v1 requires two candidates/counters, the supplied 520-paper ranges, "
            "turnout 300, and nonnegative integer vote/invalid figures totaling 300."
        )
    return data, hashlib.sha256(raw).hexdigest()


def initial_state(day: str, scenario: dict[str, Any], digest: str) -> dict[str, Any]:
    opening = datetime.combine(date.fromisoformat(day), datetime.min.time(), HKT).replace(hour=8)
    if opening + timedelta(hours=2) > datetime.now(HKT):
        raise DemoError(
            "Choose a completed past demonstration date; the default is yesterday in Hong Kong."
        )
    offsets = {
        "receipt": -30,
        "opening": 0,
        "allocation": 5,
        "snapshot": 55,
        "turnout_end": 60,
        "closing_admission": 60,
        "closing_complete": 65,
        "conversion": 70,
        "box_open": 75,
        "count": 90,
    }
    return {
        "format": 1,
        "import_id": str(uuid4()),
        "scenario_sha256": digest,
        "context": {
            "election_date": day,
            "scenario": scenario,
            "times": {
                key: (opening + timedelta(minutes=value)).isoformat()
                for key, value in offsets.items()
            },
        },
        "accounts": {},
        "steps": {},
        "stage": None,
    }


def prepare_installation(directory: Path, state: dict[str, Any], port: int) -> tuple[str, Path]:
    import yaml

    config = directory / "config.yml"
    if not config.exists():
        if "bootstrap" not in state:
            state["bootstrap"] = {
                "username": "demo_importer",
                "temporary_password": secrets.token_urlsafe(24),
                "password": secrets.token_urlsafe(24),
            }
        document = yaml.safe_load((ROOT / "config.example.yml").read_text(encoding="utf-8"))
        suffix = hashlib.sha256(str(directory).encode()).hexdigest()[:8]
        document["name"] = "election-demo-" + suffix
        document["x-election"]["server"].update(host="localhost", bind="127.0.0.1", port=port)
        document["x-election"]["storage"]["mysql"] = str(directory / "mysql")
        document["x-election"]["accounts"] = [
            {
                "username": "demo_importer",
                "display_name": "Demo Import Administrator",
                "role": "administrator",
                "password": state["bootstrap"]["temporary_password"],
            }
        ]
        for service in [document["x-image"], *document["services"].values()]:
            if "build" in service:
                service["build"]["context"] = str(ROOT)
                service["image"] = "election-demo:local"
        for name in ("configure", "initialize"):
            document["services"][name]["volumes"][0]["source"] = str(config)
        for volume in document["services"]["configure"]["volumes"]:
            if isinstance(volume, dict) and volume.get("target") == "/mysql-data":
                volume["source"] = str(directory / "mysql")
        document["services"]["db"]["volumes"][0]["source"] = str(directory / "mysql")
        document["services"]["api"]["ports"][0].update(published=port, host_ip="127.0.0.1")
        (directory / "mysql").mkdir(mode=0o700, exist_ok=True)
        private_write(directory / "state.json", json.dumps(state, ensure_ascii=False, indent=2))
        private_write(config, yaml.safe_dump(document, sort_keys=False, allow_unicode=True))
    elif "bootstrap" not in state:
        raise DemoError(
            "The demo configuration exists without its private state. Use a fresh directory."
        )
    document = yaml.safe_load(config.read_text(encoding="utf-8"))
    saved_port = document["x-election"]["server"]["port"]
    if saved_port != port:
        raise DemoError(f"This demo uses port {saved_port}; rerun with --port {saved_port}.")
    print("Starting the separate demo server (first build can take several minutes)...", flush=True)
    run_docker(config, "up", "-d", "--build", "--wait", "--wait-timeout", "240")
    ca = directory / "ca.pem"
    run_docker(config, "cp", "api:/run/election/tls/ca.pem", str(ca))
    return f"https://localhost:{saved_port}", ca


def authenticate(api: DemoAPI, args: argparse.Namespace) -> None:
    if args.command == "start":
        bootstrap = api.state["bootstrap"]
        try:
            api.login(bootstrap["username"], bootstrap["password"])
        except DemoError as error:
            if "invalid_credentials" not in str(error):
                raise
            api.login(bootstrap["username"], bootstrap["temporary_password"])
            result = api.request(
                "POST",
                "/api/auth/password",
                {
                    "current_password": bootstrap["temporary_password"],
                    "new_password": bootstrap["password"],
                },
            )
            api.token, api.password = result["token"], bootstrap["password"]
    else:
        account = api.login(args.admin, getpass.getpass("Demo server Administrator password: "))
        if account["role"] != "administrator":
            raise DemoError("Import requires an Administrator account.")
        if account["must_change_password"]:
            password = getpass.getpass("Choose its new password (12–128 characters): ")
            if password != getpass.getpass("Confirm new password: "):
                raise DemoError("Passwords did not match.")
            result = api.request(
                "POST",
                "/api/auth/password",
                {
                    "current_password": api.password,
                    "new_password": password,
                },
            )
            api.token, api.password = result["token"], password


def prepare_configuration(api: DemoAPI) -> None:
    context = api.state["context"]
    scenario = context["scenario"]
    elections = api.request("GET", "/api/elections")["items"]
    saved = api.state["steps"].get("setup/election")
    pending_create = api.state.get("pending_steps", {}).get("setup/election")
    recovering_create = pending_create and not saved
    if not recovering_create and any(not saved or row["id"] != saved["id"] for row in elections):
        raise DemoError(
            "Import requires a separate empty demo server, or this import's original "
            "dataset. Other elections were found; nothing will be overwritten."
        )
    election = api.step(
        "setup/election",
        "POST",
        "/api/elections",
        {
            "name": scenario["election_name"],
            "request_id": api.key("setup/election"),
        },
    )
    if any(row["id"] != election["id"] for row in elections):
        raise DemoError(
            "Other elections were found while recovering this demo. "
            "No existing election will be changed."
        )
    context["election_id"] = election["id"]
    base = f"/api/elections/{election['id']}"
    constituency = api.step(
        "setup/constituency",
        "POST",
        base + "/constituencies",
        {
            **scenario["constituency"],
            "request_id": api.key("setup/constituency"),
        },
    )
    context["constituency_id"] = constituency["id"]
    constituency_base = base + f"/constituencies/{constituency['id']}"
    context["candidates"] = [
        api.step(
            f"setup/candidate-{index}",
            "POST",
            constituency_base + "/candidates",
            {**row, "request_id": api.key(f"setup/candidate-{index}")},
        )
        for index, row in enumerate(scenario["candidates"], 1)
    ]
    station = api.step(
        "setup/station",
        "POST",
        constituency_base + "/stations",
        {
            **scenario["station"],
            "counting_mode": "local",
            "request_id": api.key("setup/station"),
        },
    )
    context["station_id"] = station["id"]
    context["counters"] = [
        api.step(
            f"setup/counter-{index}",
            "POST",
            constituency_base + f"/stations/{station['id']}/counters",
            {**row, "request_id": api.key(f"setup/counter-{index}")},
        )
        for index, row in enumerate(scenario["counters"], 1)
    ]
    schedule_data = {
        "election_date": context["election_date"],
        "revision": 0,
        "planned_opening_at": context["times"]["opening"],
        "planned_closing_at": context["times"]["turnout_end"],
        "reporting_interval_minutes": 60,
    }
    if (
        "setup/schedule" in api.state.get("pending_steps", {})
        and "setup/schedule" not in api.state["steps"]
    ):
        try:
            current_schedule = api.request("GET", base + "/schedule")
        except DemoError as error:
            if "schedule_not_configured" not in str(error):
                raise
        else:
            matching = all(
                current_schedule[key] == schedule_data[key]
                for key in ("election_date", "reporting_interval_minutes")
            ) and all(
                datetime.fromisoformat(current_schedule[key])
                == datetime.fromisoformat(schedule_data[key])
                for key in ("planned_opening_at", "planned_closing_at")
            )
            if current_schedule["revision"] != 1 or not matching:
                raise DemoError("The pending demo schedule differs from the saved server schedule.")
            api.state["steps"]["setup/schedule"] = current_schedule
            api.state["pending_steps"].pop("setup/schedule")
            api.save()
    api.step("setup/schedule", "PUT", base + "/schedule", schedule_data)
    api.save()


def prepare_accounts(api: DemoAPI) -> None:
    directory = api.request("GET", "/api/accounts")["items"]
    for role, (username, name) in ROLES.items():
        accounts = api.state["accounts"]
        existing = next((row for row in directory if row["username"] == username), None)
        if role not in accounts:
            if existing:
                raise DemoError(
                    f"Account {username} already exists outside this import; "
                    "use a fresh demo server."
                )
            accounts[role] = {
                "username": username,
                "temporary_password": secrets.token_urlsafe(24),
                "password": secrets.token_urlsafe(24),
                "role": role,
            }
            api.save()
        saved = accounts[role]
        station_ids = [] if role == "administrator" else [api.state["context"]["station_id"]]
        if existing and (existing["role"] != role or existing["station_ids"] != station_ids):
            raise DemoError(f"Account {username} no longer matches this demo's role/assignments.")
        if not existing:
            existing = api.request(
                "POST",
                "/api/accounts",
                {
                    "username": username,
                    "display_name": name,
                    "role": role,
                    "temporary_password": saved["temporary_password"],
                    "station_ids": station_ids,
                },
            )
        saved["id"] = existing["id"]
        # Tokens and approval payloads stay in memory rather than the import journal.
        try:
            login = api.request(
                "POST",
                "/api/auth/login",
                {
                    "username": username,
                    "password": saved["password"],
                },
            )
        except DemoError as error:
            if "invalid_credentials" not in str(error):
                raise
            login = api.request(
                "POST",
                "/api/auth/login",
                {
                    "username": username,
                    "password": saved["temporary_password"],
                },
            )
            from election.demo.client import DemoRole

            actor = DemoRole(api, login["token"], saved["temporary_password"])
            try:
                login = actor.request(
                    "POST",
                    "/api/auth/password",
                    {
                        "current_password": saved["temporary_password"],
                        "new_password": saved["password"],
                    },
                )
            finally:
                actor.token = ""
        from election.demo.client import DemoRole

        actor = DemoRole(api, login["token"], saved["password"])
        actor.request("DELETE", "/api/auth/session")
        api.save()


def write_presenter_files(api: DemoAPI, directory: Path) -> None:
    lines = [
        "# Private demo account sheet",
        "",
        f"Server: {api.server}",
        f"Stage: {api.state['stage']}",
        f"Election date (Hong Kong): {api.state['context']['election_date']}",
        "",
        "| Role | Username | Password |",
        "| --- | --- | --- |",
    ]
    for role, account in api.state["accounts"].items():
        lines.append(f"| {role} | {account['username']} | {account['password']} |")
    lines += [
        "",
        "All first-login password changes and station assignments are complete.",
        "Supervisor approvals use the Supervisor password above.",
        "This private sheet and state.json contain passwords; keep them out of shared slides.",
        "",
    ]
    private_write(directory / "ACCOUNTS.md", "\n".join(lines))


def import_demo(api: DemoAPI, stage: str) -> None:
    from election.demo.counting import prepare_counting, prepare_results
    from election.demo.polling import finish_polling, prepare_polling

    current = api.state.get("stage")
    if current and STAGES.index(stage) < STAGES.index(current):
        raise DemoError(
            f"This demo is already at {current}. Stages advance only; use a fresh directory "
            "and another port for a separate rehearsal."
        )
    prepare_configuration(api)
    prepare_accounts(api)
    context = api.state["context"]
    api.step(
        "setup/activate",
        "POST",
        f"/api/elections/{context['election_id']}/activate",
        {
            "election_revision": 1,
            "schedule_revision": 1,
        },
    )
    prepare_polling(api, context)
    if stage in ("counting", "results"):
        finish_polling(api, context)
        prepare_counting(api, context)
    if stage == "results":
        prepare_results(api, context)
        base = f"/api/workspace/constituencies/{context['constituency_id']}/results/statement"
        supervisor = api.as_role("supervisor")
        for extension in ("csv", "pdf"):
            supervisor.download(
                base + f".{extension}?locale=en",
                api.state_path.parent / f"demo-results.{extension}",
            )
    # Verify role scope through independent authenticated reads.
    for role in ("polling_officer", "counting_officer", "supervisor"):
        stations = api.as_role(role).request("GET", "/api/workspace/stations")["items"]
        if [row["station"]["id"] for row in stations] != [context["station_id"]]:
            raise DemoError("Demo station readback did not match the intended assignment.")
    api.state["stage"] = stage
    api.save()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("start", "import"):
        child = commands.add_parser(command)
        child.add_argument("--stage", choices=STAGES, default="polling")
        child.add_argument(
            "--directory",
            type=Path,
            default=ROOT / ".runtime" / ("demo" if command == "start" else "demo-import"),
        )
        child.add_argument("--scenario", type=Path, default=ROOT / "demo" / "scenario.json")
        child.add_argument(
            "--date", help="Past election date YYYY-MM-DD; defaults to yesterday in Hong Kong"
        )
        if command == "start":
            child.add_argument("--port", type=int, default=8444)
        else:
            child.add_argument("--server", required=True)
            child.add_argument("--ca", required=True, type=Path)
            child.add_argument("--admin", default="admin")
    args = parser.parse_args()
    directory = args.directory.resolve()
    api = None
    lock = directory / "import.lock"
    locked = False
    try:
        if directory != ROOT / ".runtime" and ROOT / ".runtime" not in directory.parents:
            raise DemoError("Use a demo directory under this project's ignored .runtime/ folder.")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            lock_descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise DemoError(
                "Demo import is locked. Finish the other importer before retrying. If it crashed, "
                f"remove only the stale lock file: {lock}"
            ) from None
        os.close(lock_descriptor)
        locked = True
        scenario, digest = scenario_data(args.scenario)
        state_path = directory / "state.json"
        state = (
            json.loads(state_path.read_text(encoding="utf-8"))
            if state_path.exists()
            else initial_state(
                args.date or (datetime.now(HKT).date() - timedelta(days=1)).isoformat(),
                scenario,
                digest,
            )
        )
        if state["scenario_sha256"] != digest or (
            args.date and state["context"]["election_date"] != args.date
        ):
            raise DemoError(
                "Scenario/date changed after import started. Use a fresh demo directory."
            )
        if args.command == "start":
            if not 1024 <= args.port <= 65535:
                raise DemoError("Choose a demo port between 1024 and 65535.")
            server, ca = prepare_installation(directory, state, args.port)
        else:
            server, ca = args.server.rstrip("/"), args.ca.resolve()
        identity = {"server": server, "ca_sha256": hashlib.sha256(ca.read_bytes()).hexdigest()}
        if "target" in state and state["target"] != identity:
            raise DemoError("The server or public CA differs from this import's saved target.")
        state["target"] = identity
        api = DemoAPI(server, ca, state_path, state)
        api.save()
        authenticate(api, args)
        print(f"Preparing {args.stage} stage through {server}...", flush=True)
        import_demo(api, args.stage)
        write_presenter_files(api, directory)
        print(
            f"Demo ready: {args.stage}\nServer: {server}\nPublic CA: {ca}\n"
            f"Private account sheet: {directory / 'ACCOUNTS.md'}",
            flush=True,
        )
    except (DemoError, OSError, ValueError, KeyError) as error:
        print(f"Demo preparation stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        if api is not None:
            api.close()
        if locked:
            lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
