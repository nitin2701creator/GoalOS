import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.purchase_order import router as po_router
from app.api.router import api_router
from app.api.v1.openai import build_health_payload
from app.api.v1.openai import router as openai_router
from app.dashboard.dashboard_router import router as dashboard_router
from app.db.base import Base
from app.db.session import engine, get_db

app = FastAPI(
    title="GoalOS",
    description="Enterprise AI Operating System",
    version="0.5.0",
)


def _cors_origins() -> list[str]:
    """CORS allow-list: the configured OpenWebUI origin plus dev defaults.

    Production never assumes localhost — set OPENWEBUI_BASE_URL to the
    OpenWebUI origin (e.g. ``https://openwebui.kvm.local``) and it is used
    verbatim; the defaults only cover local development.
    """
    origins = []
    openwebui = os.getenv("OPENWEBUI_BASE_URL")
    if openwebui and openwebui.strip():
        origins.append(openwebui.strip())
    origins.extend(
        [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]
    )
    return list(dict.fromkeys(origins))


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.include_router(po_router)
app.include_router(dashboard_router)
# OpenAI-compatible surface for OpenWebUI (mounted at /v1/models,
# /v1/chat/completions, /v1/health — separate from the /api namespace).
app.include_router(openai_router, prefix="/v1")


@app.on_event("startup")
def on_startup():
    # Create DB tables if they don't exist
    Base.metadata.create_all(bind=engine)


@app.get("/")
async def root():
    return {
        "name": "GoalOS",
        "status": "running",
        "version": "0.5.0",
    }


@app.get("/health")
async def health(db=Depends(get_db)):
    return build_health_payload(db)
