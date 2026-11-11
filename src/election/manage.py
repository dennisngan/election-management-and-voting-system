"""Local administration commands. Passwords never appear in CLI arguments."""

import argparse
import getpass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.config import Settings
from election.server.db import make_engine
from election.server.models import Account, AuditEvent
from election.server.security import hash_password, normalize_username


def bootstrap_account(database_url: str, username: str, display_name: str, password: str) -> None:
    username = normalize_username(username)
    if not 1 <= len(username) <= 64 or not 1 <= len(display_name) <= 120:
        raise ValueError(
            "Username and display name are required and must fit the configured limits"
        )
    if not 12 <= len(password) <= 128:
        raise ValueError("Use a password between 12 and 128 characters")
    engine = make_engine(database_url)
    try:
        with Session(engine) as db, db.begin():
            if db.scalar(select(Account).where(Account.username == username)):
                raise ValueError("Account already exists; bootstrap never overwrites credentials")
            now = datetime.now(UTC).replace(tzinfo=None)
            account = Account(
                username=username,
                display_name=display_name,
                role="administrator",
                password_hash=hash_password(password),
                must_change_password=True,
                enabled=True,
                created_at=now,
            )
            db.add(account)
            db.flush()
            db.add(
                AuditEvent(
                    actor_id=account.id,
                    action="bootstrap_account",
                    occurred_at=now,
                    details={"username": username},
                )
            )
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate")
    bootstrap = subparsers.add_parser("bootstrap")
    bootstrap.add_argument("--username", required=True)
    bootstrap.add_argument("--display-name", required=True)
    args = parser.parse_args()
    if args.command == "migrate":
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("alembic.ini"), "head")
    else:
        password = getpass.getpass("Temporary password (12–128 characters): ")
        if password != getpass.getpass("Confirm temporary password: "):
            raise SystemExit("Passwords did not match")
        bootstrap_account(Settings().database_url, args.username, args.display_name, password)
        print("Account provisioned; first sign-in requires a password change.")


if __name__ == "__main__":
    main()
