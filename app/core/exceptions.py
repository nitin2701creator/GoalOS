"""
GoalOS exception definitions.
"""

from __future__ import annotations


class GoalOSError(Exception):
    """Base exception for GoalOS."""


class ConfigurationError(GoalOSError):
    """Raised when configuration is invalid."""


class IntegrationError(GoalOSError):
    """Raised when an external integration fails."""


class ValidationError(GoalOSError):
    """Raised when supplied data fails validation."""


class AgentError(GoalOSError):
    """Raised for agent execution failures."""


class EngineError(GoalOSError):
    """Raised for engine execution failures."""
