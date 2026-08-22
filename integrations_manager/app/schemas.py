"""Pydantic schemas for the Integrations Manager API."""
from __future__ import annotations

import datetime as _dt
from pydantic import BaseModel, Field


# ── Auth ─────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    csrf_token: str

class CSRFTokenResponse(BaseModel):
    csrf_token: str


# ── Integrations ────────────────────────────────────────────────────────

class IntegrationSummary(BaseModel):
    id: int
    slug: str
    name: str
    description: str
    icon: str
    auth_type: str
    status: str
    last_connected_at: _dt.datetime | None = None
    error_message: str | None = None

class IntegrationDetail(IntegrationSummary):
    credential_fields: list[dict] = []
    has_credentials: bool = False
    has_oauth: bool = False

class CredentialField(BaseModel):
    key: str
    label: str
    type: str = "text"
    required: bool = True

class MaskedCredential(BaseModel):
    key: str
    label: str
    masked_value: str
    is_set: bool = True

class SaveCredentialsRequest(BaseModel):
    credentials: dict[str, str] = Field(..., description="Key-value pairs of credentials")

class SaveCredentialsResponse(BaseModel):
    success: bool
    message: str

class TestConnectionResponse(BaseModel):
    success: bool
    message: str
    details: dict = {}

class ConnectResponse(BaseModel):
    success: bool
    message: str
    redirect_url: str | None = None

class AccountInfoResponse(BaseModel):
    success: bool
    details: dict = {}

class DisconnectResponse(BaseModel):
    success: bool
    message: str


# ── OAuth ───────────────────────────────────────────────────────────────

class OAuthCallbackRequest(BaseModel):
    code: str
    state: str | None = None

class OAuthTokenResponse(BaseModel):
    success: bool
    message: str
    access_token_preview: str = ""


# ── Audit ───────────────────────────────────────────────────────────────

class AuditLogEntry(BaseModel):
    id: int
    integration_slug: str | None = None
    action: str
    actor: str
    details: str
    created_at: _dt.datetime
