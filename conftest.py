"""Root pytest configuration for GoalOS.

Ensures the project root is on ``sys.path`` so that the ``tests`` package
(and any sibling ``app`` imports) are importable during full collection.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The project root is the directory containing this conftest.py.
_PROJECT_ROOT = str(Path(__file__).resolve().parent)

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
