from __future__ import annotations

import ipaddress
import socket
from urllib.parse import ParseResult, urlparse

import httpx
from fastapi import HTTPException, status


def host_is_allowed(hostname: str, allowed_hosts: set[str]) -> bool:
    host = hostname.lower().rstrip(".")
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts)


def validate_url_shape(
    url: str,
    *,
    source_name: str,
    allow_http: bool = False,
) -> ParseResult:
    """Fail-closed URL shape: HTTPS (HTTP only when tests opt in), no credentials."""
    parsed = urlparse(url)
    allowed_schemes = {"https", "http"} if allow_http else {"https"}
    if parsed.scheme not in allowed_schemes or not parsed.hostname or parsed.username or parsed.password:
        if allow_http:
            detail = f"{source_name} URL must be HTTP(S) and must not contain credentials"
        else:
            detail = f"{source_name} URL must be HTTPS and must not contain credentials"
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)
    allowed_ports = {None, 80, 443} if allow_http else {None, 443}
    if parsed.scheme == "https" and parsed.port not in {None, 443}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source_name} URL port is not allowed",
        )
    if parsed.scheme == "http" and parsed.port not in {None, 80}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source_name} URL port is not allowed",
        )
    if parsed.port not in allowed_ports:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source_name} URL port is not allowed",
        )
    if _host_looks_like_literal_ip_trick(parsed.hostname):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source_name} host is not a public hostname",
        )
    return parsed


def _host_looks_like_literal_ip_trick(hostname: str) -> bool:
    host = hostname.strip("[]").lower().rstrip(".")
    if host.startswith("0x") or host.startswith("::"):
        return True
    if host.isdigit() and int(host) <= 0xFFFFFFFF:
        return True
    parts = host.split(".")
    if 1 <= len(parts) <= 4 and all(part and part.replace("x", "").isalnum() for part in parts):
        if any(
            part.startswith("0x") or (part.startswith("0") and part != "0" and part.isdigit())
            for part in parts
        ):
            return True
        if len(parts) < 4 and all(part.isdigit() for part in parts):
            return True
    return False


def reject_private_resolved_addresses(addresses: list, *, source_name: str) -> None:
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{source_name} host resolves to a private address",
            )


def resolve_public_hostname(hostname: str, *, port: int, source_name: str) -> None:
    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{source_name} host cannot be resolved",
        ) from exc
    reject_private_resolved_addresses(addresses, source_name=source_name)


def validate_public_url(
    url: str,
    allowed_hosts: set[str],
    *,
    source_name: str,
    allow_http: bool = False,
) -> str:
    """Allowlist + DNS + private-IP checks. Unknown host and private IP fail closed."""
    parsed = validate_url_shape(url, source_name=source_name, allow_http=allow_http)
    assert parsed.hostname is not None
    if not host_is_allowed(parsed.hostname, allowed_hosts):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{source_name} host is not in the allowlist",
        )
    port = 80 if parsed.scheme == "http" else 443
    resolve_public_hostname(parsed.hostname, port=port, source_name=source_name)
    return url


def require_global_response_peer(response: httpx.Response, *, source_name: str = "Feed") -> None:
    stream = response.extensions.get("network_stream")
    if stream is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{source_name} connection peer could not be verified",
        )
    server_addr = stream.get_extra_info("server_addr")
    if not isinstance(server_addr, (tuple, list)) or not server_addr:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{source_name} connection peer could not be verified",
        )
    try:
        peer_ip = ipaddress.ip_address(str(server_addr[0]))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{source_name} connection peer could not be verified",
        ) from exc
    if not peer_ip.is_global:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{source_name} connection reached a private address",
        )
