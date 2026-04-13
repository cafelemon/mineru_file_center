from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import urlencode

from ..config import Settings


class FileLinkServiceError(RuntimeError):
    pass


class FileLinkDisabledError(FileLinkServiceError):
    pass


class FileLinkSecretMissingError(FileLinkServiceError):
    pass


class FileLinkValidationError(FileLinkServiceError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class FileLinkResult:
    doc_id: str
    pdf_url: str
    expires_at: int
    expires_in: int


class FileLinkService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate_pdf_url(self, doc_id: str, expires_in: int | None = None) -> FileLinkResult:
        self._ensure_ready()
        ttl = max(1, expires_in or self.settings.file_link_expire_seconds)
        expires_at = int(time.time()) + ttl
        signature = self._sign(doc_id, expires_at)
        query = urlencode({"docId": doc_id, "exp": str(expires_at), "sig": signature})
        path = f"/files/pdf/open?{query}"
        base_url = self.settings.file_link_base_url
        pdf_url = f"{base_url}{path}" if base_url else path
        return FileLinkResult(
            doc_id=doc_id,
            pdf_url=pdf_url,
            expires_at=expires_at,
            expires_in=ttl,
        )

    def verify_pdf_url(self, doc_id: str, exp: str, sig: str) -> None:
        self._ensure_ready()
        try:
            expires_at = int(exp)
        except (TypeError, ValueError) as exc:
            raise FileLinkValidationError("invalid_exp") from exc

        if expires_at < int(time.time()):
            raise FileLinkValidationError("expired")

        expected_sig = self._sign(doc_id, expires_at)
        if not hmac.compare_digest(sig, expected_sig):
            raise FileLinkValidationError("invalid_signature")

    def _ensure_ready(self) -> None:
        if not self.settings.file_link_enabled:
            raise FileLinkDisabledError("file link is disabled")
        if not self.settings.file_link_secret:
            raise FileLinkSecretMissingError("FILE_LINK_SECRET is not configured")

    def _sign(self, doc_id: str, expires_at: int) -> str:
        payload = f"{doc_id}.{expires_at}".encode("utf-8")
        return hmac.new(
            self.settings.file_link_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
