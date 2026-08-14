# GoalOS — Deployment

GoalOS is a FastAPI backend that exposes its own OpenAI-compatible API
(`/v1/models`, `/v1/chat/completions`, `/v1/health`) for OpenWebUI, plus the
native `/api/v1/*` CRUD and `/api/v1/ai/chat` gateway. It uses SQLite for
storage and can call any OpenAI-compatible LLM gateway (default: FreeLLMAPI).

Target architecture on the KVM:

```
Internet
   |
   v
OpenWebUI :8080          (existing container — not managed by this repo)
   |
   v
GoalOS FastAPI :8000     (this repo — Docker image `goalos`)
   |
   +----> SQLite persistent database  (/data/goalos.db, goalos-data volume)
   |
   +----> FreeLLMAPI :3001  (existing KVM host service, OpenAI-compatible)
              |
              v
          LLM models
```

---

## 1. Build the application

```bash
# From the repository root:
docker compose build goalos
```

This builds the image from the included `Dockerfile` (Python 3.12-slim,
`pip install -r requirements.txt`, `uvicorn app.main:app`).

## 2. Start the application

```bash
# One-time configuration:
cp env.example .env
#   - Set GOALOS_OPENWEBUI_API_KEY to a strong random value:
#       python -c "import secrets; print(secrets.token_urlsafe(32))"
#   - Set OPENWEBUI_BASE_URL to the OpenWebUI origin for CORS
#     (e.g. http://openwebui.kvm.local:8080)
#   - Set LLM_BASE_URL / LLM_MODEL to match your LLM gateway
#     (defaults: http://host.docker.internal:3001/v1, free-llm-small)

docker compose up -d --build
```

The database file lives on the `goalos-data` Docker volume
(`sqlite:////data/goalos.db`), so it survives container restarts and rebuilds.

## 3. Initialize the database

No manual step is required. On first startup GoalOS:

1. `Base.metadata.create_all` creates every table if it does not exist.
2. `ensure_schema` applies idempotent additions (e.g. `workflows.plan`)
   to pre-existing databases.
3. The persisted scheduler worker starts (single in-process loop; due runs
   are claimed atomically in the DB).

Fresh DBs and upgrades of existing DBs are both handled automatically.

## 4. Check health

```bash
# Liveness + database + LLM configuration state:
curl http://localhost:8000/health

# Readiness (200 only when the database answers):
curl http://localhost:8000/ready

# Swagger UI:
#   http://localhost:8000/docs
```

Expected `/health` shape:

```json
{
  "status": "ok",
  "database": {"status": "healthy"},
  "llm": {"configured": true, "provider": "..."}
}
```

The LLM section reports `not_configured`/`error` without failing the health
endpoint — an unavailable gateway never breaks `/health`.

## 5. View logs

```bash
docker compose logs -f goalos
```

Log level is controlled by `GOALOS_LOG_LEVEL` (`DEBUG | INFO | WARNING |
ERROR`, default `INFO`).

## 6. Restart the application

```bash
docker compose restart goalos
```

Restarts are safe: the scheduler claims due runs atomically in SQLite, so
restarts and multiple workers never double-execute.

## 7. Stop the application

```bash
docker compose stop goalos        # keeps the database volume
# or, to remove the container too:
docker compose down               # volume is kept by default
# WARNING: this deletes the database:
# docker compose down -v
```

## 8. Run tests

```bash
# On the KVM host / dev machine (inside the repo, venv active):
python -m pytest

# Startup smoke test (boots the real app in-process on a throwaway DB and
# verifies /health, /ready, /docs, CRUD, and the OpenAI-compatible surface):
python scripts/startup_smoke.py
```

---

## OpenWebUI configuration

In OpenWebUI **Admin → Settings → Connections** add a new OpenAI-compatible
connection:

| Field        | Value                                              |
| ------------ | -------------------------------------------------- |
| URL          | `http://<kvm-ip>:8000/v1` (or `http://goalos:8000/v1` on the same Docker network) |
| API Key      | the `GOALOS_OPENWEBUI_API_KEY` value               |

## Environment variables

Full reference with defaults is in `env.example`. The critical ones:

| Variable                     | Purpose                                        | Default                         |
| ---------------------------- | ---------------------------------------------- | ------------------------------- |
| `GOALOS_DATABASE_URL`        | SQLAlchemy URL for SQLite                       | `sqlite:////data/goalos.db` (image) |
| `GOALOS_OPENWEBUI_API_KEY`   | Bearer key OpenWebUI sends on `/v1/*`          | *(required — no default)*       |
| `OPENWEBUI_BASE_URL`         | OpenWebUI origin for CORS                       | localhost dev origins only      |
| `GOALOS_LOG_LEVEL`           | Log level                                       | `INFO`                          |
| `LLM_PROVIDER`               | `openai_compatible` \| `freellm`                | `openai_compatible`             |
| `LLM_BASE_URL`               | OpenAI-compatible gateway base URL              | `http://host.docker.internal:3001/v1` |
| `LLM_API_KEY`                | Gateway key (blank if the gateway needs none)   | *(empty)*                       |
| `LLM_MODEL`                  | Model served by the gateway                     | `free-llm-small`                |
| `GOALOS_SCHEDULER_ENABLED`   | Persisted scheduler on/off                      | `1`                             |
| `GOALOS_SEARCH_PROVIDER`     | Web research provider (`duckduckgo` \| empty)   | `duckduckgo`                    |

Integration credentials (Twenty CRM, Gmail, WooCommerce, GA4, Meta) are
optional — integrations report `INTEGRATION_NOT_CONFIGURED` until their
variables are set. No secret is hard-coded anywhere in the source.
