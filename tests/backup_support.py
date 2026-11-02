"""Select a dedicated MySQL backup fixture container without changing database guards."""

import os


def mysql_test_container() -> str:
    return os.environ.get("ELECTION_TEST_MYSQL_CONTAINER", "election-system-mysql")


def mysql_test_port() -> int:
    port = int(os.environ.get("ELECTION_TEST_MYSQL_PORT", "13307"))
    assert 1 <= port <= 65535, "The explicit fixture MySQL port must be valid"
    return port
