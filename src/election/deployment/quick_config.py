"""Load the editable Compose extension without exposing configuration contents."""

import ipaddress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from election.deployment.configuration import DeploymentError, host_name
from election.server.models import Account, AuditEvent
from election.server.security import hash_password


class QuickConfigError(DeploymentError):
    """A safe fixed configuration code; never contains YAML or credentials."""

    def __init__(self) -> None:
        super().__init__("invalid_quick_configuration")


class _Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class QuickServer(_Settings):
    host: str = "localhost"
    bind: str = "127.0.0.1"
    port: int = Field(default=8443, ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        return host_name(value)

    @field_validator("bind")
    @classmethod
    def require_ip(cls, value: str) -> str:
        return str(ipaddress.ip_address(value))


class QuickStorage(_Settings):
    mysql: str = Field(default="./data/mysql", min_length=1)


class QuickAccount(_Settings):
    username: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: Literal["administrator", "polling_officer", "counting_officer", "supervisor"] = (
        "administrator"
    )
    password: SecretStr = Field(repr=False)

    @field_validator("password")
    @classmethod
    def reject_placeholder(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if "$" in raw.replace("$$", ""):
            raise ValueError("password_dollar_requires_compose_escape")
        literal = raw.replace("$$", "$")
        if not 12 <= len(literal) <= 128:
            raise ValueError("password_length")
        if literal.strip().casefold().startswith(("change_me", "replace_me", "replace_with")):
            raise ValueError("password_placeholder")
        return SecretStr(literal)

    @model_validator(mode="after")
    def default_display_name(self) -> Self:
        if self.display_name is None:
            self.display_name = self.username
        return self


class QuickConfig(_Settings):
    server: QuickServer = Field(default_factory=QuickServer)
    storage: QuickStorage = Field(default_factory=QuickStorage)
    accounts: list[QuickAccount] = Field(default_factory=list)

    @model_validator(mode="after")
    def distinct_usernames(self) -> Self:
        names = [account.username.casefold() for account in self.accounts]
        if len(set(names)) != len(names):
            raise ValueError("duplicate_usernames")
        return self


def load_quick_config(path: Path) -> QuickConfig:
    """Read only x-election settings; other top-level Compose fields remain Compose-owned."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError
        return QuickConfig.model_validate(document.get("x-election", {}))
    except (
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        RecursionError,
        yaml.YAMLError,
        DeploymentError,
    ):
        raise QuickConfigError() from None


def seed_accounts(engine: Engine, accounts: list[QuickAccount]) -> int:
    """Bootstrap all configured staff once; an existing account makes this a no-op."""
    with Session(engine) as database, database.begin():
        if database.scalar(select(Account.id).limit(1)) is not None:
            return 0
        if not any(account.role == "administrator" for account in accounts):
            raise QuickConfigError()
        now = datetime.now(UTC).replace(tzinfo=None)
        for configured in accounts:
            account = Account(
                username=configured.username,
                display_name=configured.display_name or configured.username,
                role=configured.role,
                password_hash=hash_password(configured.password.get_secret_value()),
                must_change_password=True,
                enabled=True,
                created_at=now,
            )
            database.add(account)
            database.flush()
            database.add(
                AuditEvent(
                    actor_id=account.id,
                    action="bootstrap_account",
                    occurred_at=now,
                    details={"username": configured.username},
                )
            )
    return len(accounts)
