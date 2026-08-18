"""
Google OAuth credential persistence repository.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.google_oauth_credential import GoogleOAuthCredential


class GoogleOAuthRepository:
    """Database access for the persisted Google OAuth credential."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, provider: str) -> GoogleOAuthCredential | None:
        """Return the stored credential for ``provider`` (or ``None``)."""
        statement = select(GoogleOAuthCredential).where(
            GoogleOAuthCredential.provider == provider
        )
        return self.db.scalars(statement).one_or_none()

    def upsert(
        self,
        provider: str,
        refresh_token: str,
        scopes: list[str],
    ) -> GoogleOAuthCredential:
        """Create or replace the refresh token for one provider.

        A re-run of the consent flow replaces the previous token — Google
        issues a fresh refresh token on each ``prompt=consent`` grant.
        """
        row = self.get(provider)
        if row is None:
            row = GoogleOAuthCredential(
                provider=provider,
                refresh_token=refresh_token,
                scopes=list(scopes),
            )
            self.db.add(row)
        else:
            row.refresh_token = refresh_token
            row.scopes = list(scopes)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, provider: str) -> None:
        """Remove the stored credential for ``provider``, if present."""
        row = self.get(provider)
        if row is not None:
            self.db.delete(row)
            self.db.commit()

    @staticmethod
    def to_dict(row: GoogleOAuthCredential) -> dict[str, Any]:
        """Return a safe projection (never includes token values)."""
        return {
            "provider": row.provider,
            "scopes": list(row.scopes),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
