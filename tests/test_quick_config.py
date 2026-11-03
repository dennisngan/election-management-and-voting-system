"""Quick setup consumes the editable Compose extension through its public file loader."""

from pathlib import Path

import pytest
import yaml

from election.deployment.quick_config import QuickConfigError, load_quick_config


def test_compose_file_defaults_do_not_require_account_seeding(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text("services:\n  api:\n    image: election-fixture\n", encoding="utf-8")

    config = load_quick_config(path)

    assert config.server.host == "localhost"
    assert config.server.bind == "127.0.0.1"
    assert config.server.port == 8443
    assert config.storage.mysql == "./data/mysql"
    assert config.accounts == []


def test_initial_usernames_match_desktop_and_account_api_normalization(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    account = {"username": " admin ", "password": "Initial-Private-Password42!"}
    path.write_text(yaml.safe_dump({"x-election": {"accounts": [account]}}))
    assert load_quick_config(path).accounts[0].username == "admin"
    path.write_text(
        yaml.safe_dump(
            {
                "x-election": {
                    "accounts": [
                        account,
                        {**account, "username": "admin"},
                    ]
                }
            }
        )
    )
    with pytest.raises(QuickConfigError):
        load_quick_config(path)
    path.write_text(yaml.safe_dump({"x-election": {"accounts": [{**account, "username": "   "}]}}))
    with pytest.raises(QuickConfigError):
        load_quick_config(path)


def test_real_password_is_not_rejected_for_starting_with_replacement(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "x-election": {
                    "accounts": [
                        {
                            "username": "admin",
                            "password": "Replacement-Config-Password-84!",
                        }
                    ]
                }
            }
        )
    )
    assert load_quick_config(path).accounts[0].password.get_secret_value() == (
        "Replacement-Config-Password-84!"
    )


def test_compose_dollar_escape_produces_the_literal_initial_password(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "x-election": {
                    "accounts": [
                        {
                            "username": "admin",
                            "password": "Initial$$Literal$$Password42!",
                        }
                    ]
                }
            }
        )
    )
    assert load_quick_config(path).accounts[0].password.get_secret_value() == (
        "Initial$Literal$Password42!"
    )


def test_operator_can_configure_server_storage_and_initial_staff_in_compose(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(
        """name: election-fixture
x-election:
  server:
    host: Election.INTERNAL
    bind: '::1'
    port: 18443
  storage:
    mysql: './chosen data/mysql'
  accounts:
    - username: local.admin
      password: 'Fresh-fixture-password-42!'
    - username: local.poller
      display_name: Polling colleague
      role: polling_officer
      password: 'Fresh-fixture-password-43!'
    - username: local.counter
      role: counting_officer
      password: 'Fresh-fixture-password-44!'
    - username: local.supervisor
      role: supervisor
      password: 'Fresh-fixture-password-45!'
services:
  api:
    image: election-fixture
""",
        encoding="utf-8",
    )

    config = load_quick_config(path)

    assert (config.server.host, config.server.bind, config.server.port) == (
        "election.internal",
        "::1",
        18443,
    )
    assert config.storage.mysql == "./chosen data/mysql"
    assert config.accounts[0].display_name == "local.admin"
    assert config.accounts[0].role == "administrator"
    assert config.accounts[1].display_name == "Polling colleague"
    assert [account.role for account in config.accounts] == [
        "administrator",
        "polling_officer",
        "counting_officer",
        "supervisor",
    ]
    assert config.accounts[0].password.get_secret_value() == "Fresh-fixture-password-42!"
    assert "Fresh-fixture-password" not in repr(config)
    assert "Fresh-fixture-password" not in config.model_dump_json()


@pytest.mark.parametrize(
    "settings",
    [
        pytest.param({"server": {"host": "https://private-marker.invalid/"}}, id="host-is-not-url"),
        pytest.param({"server": {"host": 42}}, id="host-is-text"),
        pytest.param({"server": {"bind": "private-marker.invalid"}}, id="bind-is-ip"),
        pytest.param({"server": {"port": 0}}, id="port-is-positive"),
        pytest.param({"server": {"port": 65536}}, id="port-upper-bound"),
        pytest.param({"server": {"port": True}}, id="port-is-not-boolean"),
        pytest.param({"storage": {"mysql": ""}}, id="storage-path-is-not-empty"),
        pytest.param({"storage": {"mysql": 42}}, id="storage-path-is-text"),
        pytest.param({"server": {"private-marker": "private-input"}}, id="unknown-server-key"),
        pytest.param({"storage": {"private-marker": "private-input"}}, id="unknown-storage-key"),
        pytest.param({"private-marker": "private-input"}, id="unknown-extension-key"),
    ],
)
def test_invalid_quick_settings_have_one_safe_error(
    tmp_path: Path,
    settings: dict[str, object],
) -> None:
    path = tmp_path / "private-input-name.yml"
    path.write_text(yaml.safe_dump({"x-election": settings}), encoding="utf-8")

    with pytest.raises(QuickConfigError) as failure:
        load_quick_config(path)

    assert str(failure.value) == "invalid_quick_configuration"
    assert "private-input" not in repr(failure.value)
    assert "private-marker" not in repr(failure.value)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"username": ""}, id="username-required"),
        pytest.param({"username": "x" * 65}, id="username-length"),
        pytest.param({"display_name": ""}, id="display-name-not-empty"),
        pytest.param({"display_name": "x" * 121}, id="display-name-length"),
        pytest.param({"role": "root"}, id="role-vocabulary"),
        pytest.param({"password": "short"}, id="password-minimum"),
        pytest.param({"password": "x" * 129}, id="password-maximum"),
        pytest.param({"password": 12345678901234}, id="password-is-text"),
        pytest.param({"password": "CHANGE_ME_admin_password"}, id="change-me-placeholder"),
        pytest.param({"password": "REPLACE_WITH_A_PASSWORD"}, id="replace-placeholder"),
        pytest.param({"private-marker": "private-input"}, id="unknown-account-key"),
    ],
)
def test_invalid_initial_accounts_never_expose_input_or_passwords(
    tmp_path: Path,
    change: dict[str, object],
) -> None:
    account = {"username": "fixture.admin", "password": "Private-input-password-42!", **change}
    path = tmp_path / "private-input-name.yml"
    path.write_text(yaml.safe_dump({"x-election": {"accounts": [account]}}), encoding="utf-8")

    with pytest.raises(QuickConfigError) as failure:
        load_quick_config(path)

    assert str(failure.value) == "invalid_quick_configuration"
    assert "Private-input-password" not in repr(failure.value)
    assert "private-input" not in repr(failure.value)


@pytest.mark.parametrize("names", [("Local.Admin", "local.admin"), ("Straße", "STRASSE")])
def test_duplicate_initial_usernames_are_rejected_case_insensitively(
    tmp_path: Path,
    names: tuple[str, str],
) -> None:
    path = tmp_path / "config.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "x-election": {
                    "accounts": [
                        {"username": name, "password": "Fresh-fixture-password-42!"}
                        for name in names
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(QuickConfigError) as failure:
        load_quick_config(path)

    assert str(failure.value) == "invalid_quick_configuration"
