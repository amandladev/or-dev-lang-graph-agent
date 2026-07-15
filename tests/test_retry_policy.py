"""Tests for RetryPolicy.classify() and RetryPolicy.get_delay().

Covers Requirement 4 of core-orchestration-test-coverage.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.application.orchestrator.retry_policy import RetryPolicy
from autopilot.domain.value_objects.error_record import ErrorType


# ---------------------------------------------------------------------------
# Property 13: Every listed retryable exception type classifies as retryable
# Validates: Requirements 4.1
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    exc_type=st.sampled_from(sorted(RetryPolicy.RETRYABLE_EXCEPTIONS, key=lambda t: t.__name__)),
    message=st.text(max_size=50),
)
def test_retryable_exception_types_classify_retryable(exc_type: type, message: str):
    """Feature: core-orchestration-test-coverage, Property 13: Every listed
    retryable exception type classifies as retryable.

    **Validates: Requirements 4.1**
    """
    policy = RetryPolicy(max_retries=3, base_delay=1.0, backoff_multiplier=2.0)
    exc = exc_type(message)
    assert policy.classify(exc) == ErrorType.RETRYABLE


# ---------------------------------------------------------------------------
# Property 14: Every listed non-retryable exception type classifies correctly
# Validates: Requirements 4.2
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    exc_type=st.sampled_from(
        sorted(RetryPolicy.NON_RETRYABLE_EXCEPTIONS, key=lambda t: t.__name__)
    ),
    message=st.text(max_size=50),
)
def test_non_retryable_exception_types_classify_non_retryable(exc_type: type, message: str):
    """Feature: core-orchestration-test-coverage, Property 14: Every listed
    non-retryable exception type classifies as non-retryable.

    **Validates: Requirements 4.2**
    """
    policy = RetryPolicy(max_retries=3, base_delay=1.0, backoff_multiplier=2.0)
    exc = exc_type(message)
    assert policy.classify(exc) == ErrorType.NON_RETRYABLE


# ---------------------------------------------------------------------------
# Property 15: Unrecognized exception types default to non-retryable
# Validates: Requirements 4.3
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    name_suffix=st.integers(min_value=0, max_value=1_000_000),
    message=st.text(max_size=50),
)
def test_unrecognized_exception_type_defaults_to_non_retryable(name_suffix: int, message: str):
    """Feature: core-orchestration-test-coverage, Property 15: Unrecognized
    exception types default to non-retryable.

    **Validates: Requirements 4.3**
    """
    policy = RetryPolicy(max_retries=3, base_delay=1.0, backoff_multiplier=2.0)
    random_exc_type = type(f"RandomError{name_suffix}", (Exception,), {})
    exc = random_exc_type(message)
    assert policy.classify(exc) == ErrorType.NON_RETRYABLE


# ---------------------------------------------------------------------------
# Property 16: Subclasses of retryable exceptions inherit retryable classification
# Validates: Requirements 4.4
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    base_type=st.sampled_from(sorted(RetryPolicy.RETRYABLE_EXCEPTIONS, key=lambda t: t.__name__)),
    message=st.text(max_size=50),
)
def test_subclass_of_retryable_type_classifies_retryable(base_type: type, message: str):
    """Feature: core-orchestration-test-coverage, Property 16: Subclasses of
    retryable exceptions inherit retryable classification.

    **Validates: Requirements 4.4**
    """
    policy = RetryPolicy(max_retries=3, base_delay=1.0, backoff_multiplier=2.0)
    sub_type = type(f"Sub{base_type.__name__}", (base_type,), {})
    exc = sub_type(message)
    assert policy.classify(exc) == ErrorType.RETRYABLE


# ---------------------------------------------------------------------------
# Property 17: Backoff delay follows the exponential formula for any attempt
# and configuration
# Validates: Requirements 4.5
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    attempt=st.integers(min_value=0, max_value=2),
    pair=st.sampled_from([(2.0, 2.0), (5.0, 3.0)]),
)
def test_get_delay_formula_holds_for_known_pairs(attempt: int, pair: tuple[float, float]):
    """Feature: core-orchestration-test-coverage, Property 17: Backoff delay
    follows the exponential formula for the two given (base_delay,
    backoff_multiplier) configurations, across attempts 0, 1, 2.

    **Validates: Requirements 4.5**
    """
    base_delay, backoff_multiplier = pair
    policy = RetryPolicy(base_delay=base_delay, backoff_multiplier=backoff_multiplier)
    expected = base_delay * (backoff_multiplier ** attempt)
    assert policy.get_delay(attempt) == expected


@settings(max_examples=100)
@given(
    attempt=st.integers(min_value=0, max_value=10),
    base_delay=st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
    backoff_multiplier=st.floats(
        min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False
    ),
)
def test_get_delay_formula_holds_generally(
    attempt: int, base_delay: float, backoff_multiplier: float
):
    """Feature: core-orchestration-test-coverage, Property 17: Backoff delay
    follows the exponential formula for any non-negative attempt number and
    any (base_delay, backoff_multiplier) configuration.

    **Validates: Requirements 4.5**
    """
    policy = RetryPolicy(base_delay=base_delay, backoff_multiplier=backoff_multiplier)
    expected = base_delay * (backoff_multiplier ** attempt)
    assert policy.get_delay(attempt) == expected


# ---------------------------------------------------------------------------
# 4.6: RETRYABLE_EXCEPTIONS and NON_RETRYABLE_EXCEPTIONS are disjoint
# Validates: Requirements 4.6
# ---------------------------------------------------------------------------


def test_retryable_and_non_retryable_sets_are_disjoint():
    """**Validates: Requirements 4.6**

    No exception type SHALL appear in both RETRYABLE_EXCEPTIONS and
    NON_RETRYABLE_EXCEPTIONS.
    """
    assert not (RetryPolicy.RETRYABLE_EXCEPTIONS & RetryPolicy.NON_RETRYABLE_EXCEPTIONS)
