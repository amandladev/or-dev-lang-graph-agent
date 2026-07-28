"""Property tests for the shared atomic JSON write helper.

Feature: safe-persistence-and-config-validation
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.infrastructure.persistence.atomic_write import atomic_write_json, atomic_write_text

json_value_strategy = st.recursive(
    st.none() | st.booleans() | st.integers(min_value=-1000, max_value=1000)
    | st.floats(allow_nan=False, allow_infinity=False) | st.text(max_size=20),
    lambda children: st.lists(children, max_size=5)
    | st.dictionaries(st.text(max_size=10), children, max_size=5),
    max_leaves=20,
)

safe_filename_strategy = st.from_regex(r"[A-Za-z0-9_-]{1,20}", fullmatch=True)


class TestAtomicWriteRoundTrip:
    """Property 1: Successful atomic write round-trips arbitrary JSON-serializable data.

    **Validates: Requirements 1.6, 2.7**
    """

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    @settings(max_examples=100)
    @given(data=json_value_strategy, filename=safe_filename_strategy)
    def test_round_trip(self, data, filename):
        path = Path(self.tmpdir) / f"{filename}.json"
        atomic_write_json(path, data)

        assert path.exists()
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data


class TestAtomicWriteFailureCleanup:
    """Property 2: Write-time failure leaves the destination untouched and cleans
    up the temp file.

    **Validates: Requirements 1.4, 2.5**
    """

    @settings(max_examples=100)
    @given(
        pre_existing=st.text(max_size=50),
        data=json_value_strategy,
    )
    def test_write_failure_leaves_destination_untouched(self, pre_existing, data):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "dest.json"
        pre_existing_bytes = pre_existing.encode("utf-8")
        path.write_bytes(pre_existing_bytes)

        def fake_dump(*args, **kwargs):
            raise ValueError("simulated write failure")

        with patch("json.dump", side_effect=fake_dump):
            with pytest.raises(ValueError):
                atomic_write_json(path, data)

        assert path.read_bytes() == pre_existing_bytes

        remaining_tmp_files = [
            f for f in os.listdir(tmpdir) if f.endswith(".tmp")
        ]
        assert remaining_tmp_files == []


class TestAtomicWriteReplaceFailure:
    """Property 3: Replace-time failure leaves both the temp file and destination
    untouched.

    **Validates: Requirements 1.5, 2.6**
    """

    @settings(max_examples=100)
    @given(
        pre_existing=st.text(max_size=50),
        data=json_value_strategy,
    )
    def test_replace_failure_leaves_temp_and_destination(self, pre_existing, data):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "dest.json"
        pre_existing_bytes = pre_existing.encode("utf-8")
        path.write_bytes(pre_existing_bytes)

        def fake_replace(*args, **kwargs):
            raise OSError("simulated replace failure")

        with patch(
            "autopilot.infrastructure.persistence.atomic_write.os.replace",
            side_effect=fake_replace,
        ):
            with pytest.raises(OSError):
                atomic_write_json(path, data)

        assert path.read_bytes() == pre_existing_bytes

        remaining_tmp_files = [
            f for f in os.listdir(tmpdir) if f.endswith(".tmp")
        ]
        assert len(remaining_tmp_files) == 1


class TestAtomicWriteTextRoundTrip:
    """atomic_write_text mirrors atomic_write_json's guarantees for callers
    that already hold a serialized string (e.g. a custom JSON encoder)."""

    def test_round_trip(self):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "state.json"
        atomic_write_text(path, '{"a": 1}')

        assert path.read_text(encoding="utf-8") == '{"a": 1}'

    def test_write_failure_leaves_destination_untouched_and_no_tmp_left(self):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "dest.json"
        path.write_bytes(b"pre-existing")

        with patch(
            "autopilot.infrastructure.persistence.atomic_write.os.fdopen",
            side_effect=OSError("disk full"),
        ):
            with pytest.raises(OSError):
                atomic_write_text(path, "new content")

        assert path.read_bytes() == b"pre-existing"
        remaining_tmp_files = [f for f in os.listdir(tmpdir) if f.endswith(".tmp")]
        assert remaining_tmp_files == []
