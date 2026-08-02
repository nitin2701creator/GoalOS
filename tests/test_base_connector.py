"""Tests for the base connector contract."""

import pytest

from app.integrations.base_connector import BaseConnector


def test_base_connector_cannot_be_instantiated() -> None:
    """The connector contract is abstract."""

    with pytest.raises(TypeError):
        BaseConnector()


def test_base_connector_requires_lifecycle_methods() -> None:
    """All requested lifecycle methods remain abstract."""

    assert BaseConnector.__abstractmethods__ == {"connect", "disconnect", "health"}
