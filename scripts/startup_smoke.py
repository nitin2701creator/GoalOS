"""GoalOS startup smoke test.

Boots the real application in-process (running the FastAPI startup
events: table creation, schema additions, scheduler worker) against a
throwaway SQLite database and verifies the deployment-critical surface:

- /, /health, /ready, /docs, /openapi.json
- Goals / Objectives / Projects / Tasks CRUD
- /v1/models + /v1/health with the OpenWebUI bearer key
- /v1/chat/completions answers gracefully with no LLM configured

Usage (from the repository root, with the venv active):

    .venv/bin/python scripts/startup_smoke.py

Exits non-zero on the first failed check. The temporary database is
removed afterwards.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

# Make the repository root importable when run as ``scripts/startup_smoke.py``.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# --- Environment before importing the app ---------------------------
_TMP_DIR = Path(tempfile.mkdtemp(prefix="goalos-smoke-"))
_DB_PATH = _TMP_DIR / "goalos.db"
os.environ["GOALOS_DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ.setdefault("GOALOS_OPENWEBUI_API_KEY", "smoke-test-key")
os.environ.setdefault("GOALOS_LOG_LEVEL", "WARNING")
# Integration checks below must stay hermetic: force credential-backed
# integrations into their honest Not Configured state.
os.environ.pop("GOALOS_TWENTY_BASE_URL", None)
os.environ.pop("GOALOS_TWENTY_API_KEY", None)
os.environ.pop("GOALOS_SEARCH_PROVIDER", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

_FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        _FAILURES.append(name)


def main() -> int:
    api_key = os.environ["GOALOS_OPENWEBUI_API_KEY"]
    headers = {"Authorization": f"Bearer {api_key}"}

    with TestClient(app) as client:  # runs startup + shutdown events
        # --- Liveness / readiness / docs -----------------------------
        r = client.get("/")
        check("GET /", r.status_code == 200 and r.json().get("status") == "running",
              f"status={r.status_code}")

        r = client.get("/health")
        check("GET /health", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200:
            body = r.json()
            check("/health reports db healthy",
                  body.get("database", {}).get("status") == "healthy")
            check("/health reports llm state",
                  body.get("llm", {}).get("status") in {"configured", "not_configured", "error"},
                  f"llm={body.get('llm')}")

        r = client.get("/ready")
        check("GET /ready", r.status_code == 200 and r.json().get("database") == "healthy",
              f"status={r.status_code} body={r.text[:120]}")

        r = client.get("/docs")
        check("GET /docs", r.status_code == 200, f"status={r.status_code}")

        r = client.get("/openapi.json")
        check("GET /openapi.json", r.status_code == 200, f"status={r.status_code}")
        paths = set(r.json().get("paths", {})) if r.status_code == 200 else set()
        for expected in (
            "/api/v1/goals",
            "/api/v1/objectives",
            "/api/v1/projects",
            "/api/v1/tasks",
            "/api/v1/integrations",
            "/api/v1/ai/chat",
            "/v1/chat/completions",
            "/v1/models",
            "/v1/health",
        ):
            check(f"openapi path {expected}", any(p.startswith(expected) for p in paths))

        # --- CRUD smoke ----------------------------------------------
        goal_id = _crud(client, "goals", {
            "title": "Smoke goal",
            "description": "deploy smoke",
            "executive_owner": "smoke-owner",
            "department": "Engineering",
            "priority": "high",
        })
        _crud(client, "objectives",
              {"title": "Smoke objective", "description": "deploy smoke", "goal_id": goal_id})
        project_id = _crud(client, "projects", {
            "title": "Smoke project",
            "description": "deploy smoke",
            "owner": "smoke-owner",
            "department": "Engineering",
            "priority": "high",
        })
        _crud(client, "tasks", {
            "project_id": project_id,
            "title": "Smoke task",
            "description": "deploy smoke",
            "priority": "high",
        })

        # --- OpenAI-compatible surface -------------------------------
        r = client.get("/v1/models", headers=headers)
        check("GET /v1/models (bearer)", r.status_code == 200, f"status={r.status_code}")

        r = client.get("/v1/models")
        check("GET /v1/models without key -> 401/503", r.status_code in (401, 503),
              f"status={r.status_code}")

        r = client.get("/v1/health", headers=headers)
        check("GET /v1/health (bearer)", r.status_code == 200, f"status={r.status_code}")

        # Chat with NO LLM configured must answer deterministically,
        # never 500 (LLM gateway unavailable / unconfigured is graceful).
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "model": "goalos",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        ok = bool(r.status_code == 200 and r.json().get("choices", [{}])[0]
                  .get("message", {}).get("content"))
        check("POST /v1/chat/completions without LLM is graceful",
              ok, f"status={r.status_code} body={r.text[:200]}")

        # --- Integration execution foundation ------------------------
        r = client.get("/api/v1/integrations")
        body = r.json() if r.status_code == 200 else {}
        check("GET /api/v1/integrations",
              r.status_code == 200 and body.get("total", 0) >= 9,
              f"status={r.status_code} body={r.text[:160]}")
        web = next(
            (item for item in body.get("integrations", []) if item.get("name") == "web"),
            {},
        )
        check("integration registry exposes type/enabled/capabilities",
              web.get("integration_type") == "web"
              and web.get("enabled") is True
              and "web.search" in web.get("capabilities", []),
              f"web={web}")

        # Health/test on an unconfigured integration is honest.
        r = client.post("/api/v1/integrations/twenty/test")
        check("POST /api/v1/integrations/twenty/test -> Not Configured",
              r.status_code == 200 and r.json().get("status") == "Not Configured",
              f"status={r.status_code} body={r.text[:160]}")

        # Executing an unconfigured integration reports INTEGRATION_NOT_CONFIGURED,
        # never a fake success, and needs no network.
        r = client.post(
            "/api/v1/integrations/twenty/execute",
            json={
                "capability": "twenty.search_people",
                "permissions": ["READ_CRM"],
            },
        )
        check("POST /api/v1/integrations/twenty/execute honest failure",
              r.status_code == 200
              and r.json().get("status") == "INTEGRATION_NOT_CONFIGURED",
              f"status={r.status_code} body={r.text[:200]}")

    shutil.rmtree(_TMP_DIR, ignore_errors=True)

    print()
    if _FAILURES:
        print(f"SMOKE FAILED: {len(_FAILURES)} check(s) failed")
        for name in _FAILURES:
            print(f"  - {name}")
        return 1
    print("SMOKE PASSED: all startup checks succeeded")
    return 0


def _crud(client: TestClient, resource: str, payload: dict) -> str | None:
    """Create + list + fetch one entity; returns its id when created."""
    r = client.post(f"/api/v1/{resource}", json=payload)
    check(f"POST /api/v1/{resource}", r.status_code in (200, 201),
          f"status={r.status_code} body={r.text[:160]}")
    if r.status_code not in (200, 201):
        return None
    entity_id = r.json().get("id")
    r = client.get(f"/api/v1/{resource}")
    check(f"GET /api/v1/{resource}", r.status_code == 200, f"status={r.status_code}")
    if entity_id:
        r = client.get(f"/api/v1/{resource}/{entity_id}")
        check(f"GET /api/v1/{resource}/{{id}}", r.status_code == 200, f"status={r.status_code}")
    return entity_id


if __name__ == "__main__":
    sys.exit(main())
