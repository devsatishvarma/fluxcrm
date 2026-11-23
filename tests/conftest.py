"""Shared pytest fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _disable_mfa_by_default(settings):
    """Existing suites assume password-only sign-in. MFA tests turn this on."""
    settings.MFA_REQUIRED = False
