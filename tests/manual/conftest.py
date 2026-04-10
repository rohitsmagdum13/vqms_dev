"""Exclude manual tests from pytest collection.

Manual tests require real cloud services (Bedrock, PostgreSQL via SSH tunnel)
and are meant to be run standalone:
    uv run python tests/manual/test_bedrock_connection.py

They are NOT part of the automated test suite.
"""

collect_ignore_glob = ["test_*.py"]
