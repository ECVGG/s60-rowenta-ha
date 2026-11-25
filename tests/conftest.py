import pytest


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations):
    """Allow loading the integration under test."""
