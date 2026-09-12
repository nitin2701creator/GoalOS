"""Root pytest configuration for GoalOS.

Ensures the project root is on ``sys.path`` so that the ``tests`` package
(and any sibling ``app`` imports) are importable during full collection.

Also seeds the shared Integrations Manager test environment **before any
test module is imported** so the pydantic ``settings`` singleton is
deterministic regardless of import order (see ``config.py``).
"""

from __future__ import annotations

import os
import secrets
import sys
import tempfile
from pathlib import Path

# The project root is the directory containing this conftest.py.
_PROJECT_ROOT = str(Path(__file__).resolve().parent)

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── Shared Integrations Manager test environment ──────────────────────────
# A file-backed sqlite DB keeps the app's tables visible to every thread that
# touches ``app.state.db`` (TestClient runs the app on its own thread). These
# values must match the literals asserted inside ``tests/test_im_oauth_flow.py``
# and ``tests/test_im_oauth_routes.py``.
os.environ.setdefault("IM_ENCRYPTION_KEY", secrets.token_hex(32))
os.environ.setdefault(
    "IM_DATABASE_URL",
    f"sqlite:///{os.path.join(tempfile.gettempdir(), 'goalos_im_test.db')}",
)
os.environ.setdefault("IM_ADMIN_USERNAME", "testadmin")
os.environ.setdefault("IM_ADMIN_PASSWORD", "testpass123")
os.environ.setdefault("IM_JWT_SECRET", "im-test-jwt-secret")
os.environ.setdefault("TWITTER_CLIENT_ID", "tw-test-client-id")
os.environ.setdefault("TWITTER_CLIENT_SECRET", "tw-test-client-secret")
os.environ.setdefault("GOOGLE_CLIENT_ID", "ga-test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "ga-test-client-secret")
os.environ.setdefault("LINKEDIN_CLIENT_ID", "li-test-client-id")
os.environ.setdefault("LINKEDIN_CLIENT_SECRET", "li-test-client-secret")
os.environ.setdefault("REDDIT_CLIENT_ID", "rd-test-client-id")
os.environ.setdefault("REDDIT_CLIENT_SECRET", "rd-test-client-secret")
os.environ.setdefault("META_APP_ID", "meta-test-app-id")
os.environ.setdefault("META_APP_SECRET", "meta-test-app-secret")
