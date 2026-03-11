"""Test fixtures for Open Brain.

Overrides config to use open_brain_test database and truncates
the memories table between tests.
"""

import pytest
from open_brain import config

# Override database name for all tests
config.DB_NAME = "open_brain_test"


@pytest.fixture(autouse=True)
def _clean_db():
    """Truncate the memories table before each test."""
    import psycopg2
    conn = psycopg2.connect(config.dsn("admin"))
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("TRUNCATE memories")
        cur.execute("TRUNCATE epochs")
    conn.close()
    yield
