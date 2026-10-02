"""Local principal authentication for the single-host deployment.

Principals are registered in the workspace with the SHA-256 of a secret that
is never stored in the journal. A credential is (principal_id, secret). This
is caller authentication for the local API; it is not a network identity
system and does not replace OS access control on the workspace directory.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from ..contracts.errors import Code, GabrielError


def new_secret() -> str:
    return secrets.token_hex(32)


def secret_digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


class Credential:
    __slots__ = ("principal_id", "_secret")

    def __init__(self, principal_id: str, secret: str):
        self.principal_id = principal_id
        self._secret = secret

    def digest(self) -> str:
        return secret_digest(self._secret)

    def __repr__(self):  # never expose the secret
        return "Credential(%r)" % self.principal_id


def authenticate(registry: dict, credential: Credential) -> str:
    """registry: {principal_id: secret_sha256}. Returns the principal id."""
    stored = registry.get(credential.principal_id)
    if stored is None or not hmac.compare_digest(stored, credential.digest()):
        raise GabrielError(Code.POLICY_DENIED, "principal authentication failed", obj=credential.principal_id)
    return credential.principal_id
