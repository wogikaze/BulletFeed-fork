from __future__ import annotations

import hashlib
import hmac
from typing import Any


def verify_github_webhook_signature(
    *,
    secret: str,
    body: bytes,
    signature_header: str | None,
) -> bool:
    if not secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def release_from_webhook_payload(payload: object) -> tuple[str, str, dict[str, Any]] | None:
    if not isinstance(payload, dict):
        return None
    release = payload.get("release")
    repository = payload.get("repository")
    if not isinstance(release, dict) or not isinstance(repository, dict):
        return None
    owner, name = _repository_identity(repository)
    if owner is None or name is None:
        return None
    return owner, name, release


def _repository_identity(repository: dict[str, Any]) -> tuple[str | None, str | None]:
    owner = repository.get("owner")
    owner_login = owner.get("login") if isinstance(owner, dict) else None
    name = repository.get("name")
    if isinstance(owner_login, str) and owner_login and isinstance(name, str) and name:
        return owner_login, name
    full_name = repository.get("full_name")
    if isinstance(full_name, str) and "/" in full_name:
        owner_part, name_part = full_name.split("/", 1)
        if owner_part and name_part:
            return owner_part, name_part
    return None, None
