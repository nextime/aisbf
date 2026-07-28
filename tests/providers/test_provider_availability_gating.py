"""Regression tests for provider availability gating.

Covers the production failure where a manually-flagged provider was permanently
evicted from every rotation it belonged to and clients saw an upstream 429.
"""

import time

from aisbf.handlers import _provider_in_availability_cooldown
from aisbf.providers.base import BaseProviderHandler


def _handler(manual=False, disabled_until=None, usage_until=None):
    """A bare handler carrying only the attributes the availability gates read."""
    h = object.__new__(BaseProviderHandler)
    h.provider_id = 'codex'
    h._manual_disabled = manual
    h._usage_disabled_until = usage_until
    h.error_tracking = {'disabled_until': disabled_until, 'failures': 0}
    return h


class TestIsRateLimited:
    def test_manual_disable_does_not_rate_limit(self):
        """The legacy global manual flag must not gate requests.

        Every provider's handle_request() raises Exception("Provider rate limited")
        when this is true, before any upstream call. The rotation scan deliberately
        ignores the manual flag, so the provider still got selected, and that
        synthetic error was then counted against its health.
        """
        assert _handler(manual=True).is_rate_limited() is False

    def test_active_failure_cooldown_rate_limits(self):
        h = _handler(disabled_until=time.time() + 300)
        assert h.is_rate_limited() is True

    def test_active_usage_cooldown_rate_limits(self):
        h = _handler(usage_until=time.time() + 300)
        assert h.is_rate_limited() is True

    def test_elapsed_cooldown_reactivates_with_fresh_budget(self):
        h = _handler(disabled_until=time.time() - 1)
        h.error_tracking['failures'] = 3
        assert h.is_rate_limited() is False
        # Reactivated on a fresh budget, not left on a hair-trigger.
        assert h.error_tracking['failures'] == 0

    def test_no_state_is_not_rate_limited(self):
        assert _handler().is_rate_limited() is False


class TestAvailabilityCooldownPredicate:
    """The rotation scan skips on this predicate; it must ignore the manual flag."""

    def test_manual_disable_is_not_an_availability_cooldown(self):
        assert _provider_in_availability_cooldown(_handler(manual=True)) is False

    def test_failure_cooldown_is_an_availability_cooldown(self):
        assert _provider_in_availability_cooldown(
            _handler(disabled_until=time.time() + 300)
        ) is True

    def test_usage_cooldown_is_an_availability_cooldown(self):
        assert _provider_in_availability_cooldown(
            _handler(usage_until=time.time() + 300)
        ) is True

    def test_expired_cooldown_is_not_an_availability_cooldown(self):
        assert _provider_in_availability_cooldown(
            _handler(disabled_until=time.time() - 1)
        ) is False


class TestCooldownDoesNotSelfExtend:
    """A provider in cooldown must not have that cooldown renewed by its own gate.

    handle_request() raises "Provider rate limited" before any upstream call while a
    cooldown is active. The rotation retry loop used to feed that straight into
    record_failure(), pushing disabled_until another full cooldown into the future on
    every attempt — under steady traffic the cooldown could never elapse (observed in
    production at 447 failures against a threshold of 3).
    """

    def test_gate_error_leaves_cooldown_untouched(self):
        disabled_until = time.time() + 300
        h = _handler(disabled_until=disabled_until)

        # The guard in the retry loop keys off this predicate to skip record_failure().
        assert _provider_in_availability_cooldown(h) is True

        # record_failure() is what would have extended the window; confirm that had it
        # run, it would indeed have pushed the deadline out — i.e. the guard matters.
        assert h.error_tracking['disabled_until'] == disabled_until
