"""Unit tests for canonical connection-state resolution.

Verifies the effective-status vocabulary: not configured, authorization
required, configured, connected, expired, and disabled.
"""
from __future__ import annotations

import datetime as _dt
import os
import secrets

os.environ.setdefault("IM_ENCRYPTION_KEY", secrets.token_hex(32))
os.environ.setdefault("IM_DATABASE_URL", "sqlite:///:memory:")

import pytest  # noqa: E402

from integrations_manager.app.models import (  # noqa: E402
    ConnectionStatus,
    Integration,
    OAuthToken,
    create_db_engine,
    get_session_factory,
    init_db,
)
from integrations_manager.app.routers.integrations import _effective_status  # noqa: E402
from integrations_manager.app.status import (  # noqa: E402
    AUTH_FAILED,
    AUTH_REQUIRED,
    CONFIGURED,
    CONNECTED,
    DISABLED,
    EXPIRED,
    NOT_CONFIGURED,
    is_unhealthy,
)


@pytest.fixture
def db():
    engine = create_db_engine("sqlite:///:memory:")
    init_db(engine)
    session = get_session_factory(engine)()
    yield session
    session.close()
    engine.dispose()


def _integ(db, slug="twitter", auth_type="oauth2", enabled=True, status=None):
    row = Integration(slug=slug, name=slug, auth_type=auth_type, is_enabled=enabled)
    db.add(row)
    db.commit()
    db.refresh(row)
    status_row = None
    if status is not None:
        status_row = ConnectionStatus(integration_id=row.id, status=status)
        db.add(status_row)
        db.commit()
        db.refresh(status_row)
    return row, status_row


def _token(db, integ, expires_at):
    from integrations_manager.app.encryption import CredentialEncryption

    enc = CredentialEncryption()
    row = OAuthToken(
        integration_id=integ.id,
        provider=integ.slug,
        encrypted_access_token=enc.encrypt("access"),
        encrypted_refresh_token=enc.encrypt("refresh"),
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()


class TestVocabulary:
    def test_unhealthy_classification(self):
        assert is_unhealthy(EXPIRED)
        assert is_unhealthy(AUTH_FAILED)
        assert is_unhealthy("unreachable")
        assert not is_unhealthy(CONNECTED)
        assert not is_unhealthy(NOT_CONFIGURED)
        assert not is_unhealthy(CONFIGURED)


class TestEffectiveStatus:
    def test_disabled_wins(self, db):
        integ, status_row = _integ(db, status=CONNECTED, enabled=False)
        assert _effective_status(db, integ, status_row) == DISABLED

    def test_api_key_not_configured(self, db):
        integ, status_row = _integ(db, auth_type="api_key", status=None)
        assert _effective_status(db, integ, status_row) == NOT_CONFIGURED

    def test_api_key_configured(self, db):
        integ, status_row = _integ(db, auth_type="api_key", status=CONFIGURED)
        assert _effective_status(db, integ, status_row) == CONFIGURED

    def test_oauth_without_token_is_auth_required(self, db):
        integ, status_row = _integ(db, status=None)
        assert _effective_status(db, integ, status_row) == AUTH_REQUIRED

    def test_oauth_auth_required_kept(self, db):
        integ, status_row = _integ(db, status=AUTH_REQUIRED)
        assert _effective_status(db, integ, status_row) == AUTH_REQUIRED

    def test_oauth_with_token_connected(self, db):
        integ, status_row = _integ(db, status=CONNECTED)
        _token(db, integ, _dt.datetime.utcnow() + _dt.timedelta(hours=1))
        assert _effective_status(db, integ, status_row) == CONNECTED

    def test_oauth_expired_token_reports_expired(self, db):
        integ, status_row = _integ(db, status=CONNECTED)
        _token(db, integ, _dt.datetime.utcnow() - _dt.timedelta(seconds=1))
        assert _effective_status(db, integ, status_row) == EXPIRED

    def test_oauth_with_token_but_stale_low_state_configured(self, db):
        integ, status_row = _integ(db, status=NOT_CONFIGURED)
        _token(db, integ, _dt.datetime.utcnow() + _dt.timedelta(hours=1))
        assert _effective_status(db, integ, status_row) == CONFIGURED