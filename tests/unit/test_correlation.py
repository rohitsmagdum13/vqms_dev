"""Tests for correlation and identifier generation.

Verifies UUID4 format, query ID format (VQ-YYYY-NNNN),
and uniqueness of generated identifiers.
"""

from __future__ import annotations

import re
import uuid

from src.utils.correlation import (
    generate_correlation_id,
    generate_execution_id,
    generate_query_id,
)


class TestGenerateCorrelationId:
    """Test correlation ID generation."""

    def test_returns_valid_uuid4(self):
        cid = generate_correlation_id()
        parsed = uuid.UUID(cid, version=4)
        assert str(parsed) == cid

    def test_generates_unique_ids(self):
        ids = {generate_correlation_id() for _ in range(100)}
        assert len(ids) == 100


class TestGenerateExecutionId:
    """Test execution ID generation."""

    def test_returns_valid_uuid4(self):
        eid = generate_execution_id()
        parsed = uuid.UUID(eid, version=4)
        assert str(parsed) == eid

    def test_generates_unique_ids(self):
        ids = {generate_execution_id() for _ in range(100)}
        assert len(ids) == 100


class TestGenerateQueryId:
    """Test human-readable query ID generation."""

    def test_default_format(self):
        qid = generate_query_id()
        # Should match VQ-YYYY-NNNN pattern
        assert re.match(r"^VQ-\d{4}-\d{4}$", qid)

    def test_custom_prefix(self):
        qid = generate_query_id(prefix="TEST")
        assert qid.startswith("TEST-")
        assert re.match(r"^TEST-\d{4}-\d{4}$", qid)

    def test_year_is_current(self):
        qid = generate_query_id()
        year_part = qid.split("-")[1]
        # Year should be 4 digits (current year)
        assert len(year_part) == 4
        assert int(year_part) >= 2024

    def test_generates_unique_ids(self):
        # With 10000 possible values, 50 IDs should be mostly unique
        ids = {generate_query_id() for _ in range(50)}
        # Allow some collisions since we use random (not sequence)
        assert len(ids) >= 40
