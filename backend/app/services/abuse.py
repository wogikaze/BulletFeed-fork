import hashlib

from fastapi import Request


def request_client_key(request: Request) -> str:
    """Return a stable, non-plaintext key for the request peer address."""
    host = request.client.host if request.client is not None else "unknown"
    digest = hashlib.sha256(host.encode("utf-8")).hexdigest()
    return f"client_{digest}"
