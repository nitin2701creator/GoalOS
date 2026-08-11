# GoalOS production image for the KVM.
#
# GoalOS is fully autonomous: the OpenWebUI-compatible API drives the
# agent factory, workflow orchestrator, and integration connectors. No
# Aider, Codex, or VS Code is required at runtime.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install runtime dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY app ./app

# Persistent database lives on a mounted volume in production.
ENV GOALOS_DATABASE_URL=sqlite:////data/goalos.db

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
