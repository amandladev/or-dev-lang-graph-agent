"""Property and unit tests for config_sanity_validator.

Feature: safe-persistence-and-config-validation
"""

import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.infrastructure.validators import (
    ValidationResult,
    config_sanity_validator,
    validate_environment,
)


@dataclass
class _FakeConfig:
    workspace_location: str
    vault_location: str


blank_string_strategy = st.text(alphabet=" \t\n", min_size=0, max_size=10)
non_blank_strategy = st.text(min_size=1, max_size=20).filter(lambda s: s.strip() != "")


class TestBlankFieldRejection:
    """Property 10: Blank location fields are rejected and validity reflects
    error state.

    **Validates: Requirements 4.2, 4.3, 4.7**
    """

    @settings(max_examples=100)
    @given(workspace=blank_string_strategy, vault=non_blank_strategy)
    def test_blank_workspace_rejected(self, workspace, vault):
        config = _FakeConfig(workspace_location=workspace, vault_location=vault)
        result = config_sanity_validator(config)

        assert any("workspace_location" in e for e in result.errors)
        assert result.valid == (len(result.errors) == 0)

    @settings(max_examples=100)
    @given(workspace=non_blank_strategy, vault=blank_string_strategy)
    def test_blank_vault_rejected(self, workspace, vault):
        tmpdir = tempfile.mkdtemp()
        workspace_path = os.path.join(tmpdir, workspace.strip("/") or "ws")
        config = _FakeConfig(workspace_location=workspace_path, vault_location=vault)
        result = config_sanity_validator(config)

        assert any("vault_location" in e for e in result.errors)
        assert result.valid == (len(result.errors) == 0)

    @settings(max_examples=100)
    @given(workspace=blank_string_strategy, vault=blank_string_strategy)
    def test_both_blank_rejected(self, workspace, vault):
        config = _FakeConfig(workspace_location=workspace, vault_location=vault)
        result = config_sanity_validator(config)

        assert any("workspace_location" in e for e in result.errors)
        assert any("vault_location" in e for e in result.errors)
        assert result.valid == (len(result.errors) == 0)
        assert result.valid is False


segment_strategy = st.from_regex(r"[A-Za-z0-9_-]{1,10}", fullmatch=True)


class TestCreatabilityModel:
    """Property 11: Workspace creatability check matches the nearest-existing-
    ancestor model, without side effects.

    **Validates: Requirements 4.4, 4.5, 4.6**
    """

    @settings(max_examples=100)
    @given(
        segments=st.lists(segment_strategy, min_size=1, max_size=5),
        precreate_count=st.integers(min_value=0, max_value=5),
        remove_write=st.booleans(),
        occupy_with_file=st.booleans(),
    )
    def test_creatability_matches_reference(
        self, segments, precreate_count, remove_write, occupy_with_file
    ):
        root = Path(tempfile.mkdtemp())
        precreate_count = min(precreate_count, len(segments))

        current = root
        for i in range(precreate_count):
            current = current / segments[i]
            if i == precreate_count - 1 and occupy_with_file and precreate_count == len(segments):
                # Occupy the target path itself with a plain file.
                current.write_text("occupied")
            else:
                current.mkdir(exist_ok=True)

        target = root
        for seg in segments:
            target = target / seg

        # Determine nearest existing ancestor for reference computation.
        ancestor = target.parent
        while not ancestor.exists() and ancestor != ancestor.parent:
            ancestor = ancestor.parent

        chmod_applied = False
        if remove_write and ancestor.exists() and ancestor.is_dir() and ancestor != root.parent:
            try:
                os.chmod(ancestor, stat.S_IREAD | stat.S_IEXEC)
                chmod_applied = True
            except OSError:
                chmod_applied = False

        try:
            # Independent reference expectation.
            if target.exists():
                expected_creatable = target.is_dir()
            else:
                ref_ancestor = target.parent
                while not ref_ancestor.exists() and ref_ancestor != ref_ancestor.parent:
                    ref_ancestor = ref_ancestor.parent
                expected_creatable = (
                    ref_ancestor.exists()
                    and ref_ancestor.is_dir()
                    and os.access(ref_ancestor, os.W_OK)
                )

            config = _FakeConfig(
                workspace_location=str(target), vault_location="/tmp/vault"
            )
            result = config_sanity_validator(config)

            assert result.valid == expected_creatable
            if not expected_creatable:
                assert any(
                    "workspace_location is not creatable" in e for e in result.errors
                )

            # No side effects: the target path must not exist unless it
            # existed prior to validation (pre-created above).
            if precreate_count < len(segments) or (
                precreate_count == len(segments) and occupy_with_file
            ):
                pass
            assert target.exists() == (
                precreate_count == len(segments)
            )
        finally:
            if chmod_applied:
                os.chmod(ancestor, stat.S_IRWXU)


class TestConfigSanityValidatorIndependence:
    """Unit tests for config_sanity_validator independence from
    validate_environment.

    **Validates: Requirements 4.1, 4.8**
    """

    def test_is_distinct_callable_returning_validation_result(self):
        assert config_sanity_validator is not validate_environment
        tmpdir = tempfile.mkdtemp()
        config = _FakeConfig(
            workspace_location=os.path.join(tmpdir, "ws"),
            vault_location="/tmp/vault",
        )
        result = config_sanity_validator(config)
        assert isinstance(result, ValidationResult)

    def test_never_calls_shutil_which_or_validate_environment(self):
        tmpdir = tempfile.mkdtemp()
        config = _FakeConfig(
            workspace_location=os.path.join(tmpdir, "ws"),
            vault_location="/tmp/vault",
        )
        with patch("shutil.which") as mock_which, patch(
            "autopilot.infrastructure.validators.validate_environment"
        ) as mock_validate_env:
            config_sanity_validator(config)
            mock_which.assert_not_called()
            mock_validate_env.assert_not_called()
