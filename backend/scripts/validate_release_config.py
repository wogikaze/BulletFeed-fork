"""Fail-closed validation of release stack configuration before compose up."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet

_PLACEHOLDERS = frozenset(
    {
        "",
        "change-me",
        "changeme",
        "example",
        "todo",
        "replace-me",
    }
)


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _looks_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered in _PLACEHOLDERS or lowered.startswith("changeme")


def validate_release_env(env_path: Path) -> list[str]:
    errors: list[str] = []
    if not env_path.is_file():
        return [f"missing env file: {env_path}"]

    file_values = _load_env_file(env_path)

    required_file_keys = (
        "BULLETFEED_GITHUB_CLIENT_ID",
        "BULLETFEED_GITHUB_CLIENT_SECRET",
        "BULLETFEED_TOKEN_ENCRYPTION_KEY",
        "BULLETFEED_DATABASE_PATH",
    )
    for key in required_file_keys:
        value = file_values.get(key, "")
        if not value or _looks_placeholder(value):
            errors.append(f"{key} is empty or placeholder")

    token_key = file_values.get("BULLETFEED_TOKEN_ENCRYPTION_KEY", "")
    if token_key and not _looks_placeholder(token_key):
        try:
            Fernet(token_key.encode("utf-8"))
        except Exception:
            errors.append("BULLETFEED_TOKEN_ENCRYPTION_KEY is not a valid Fernet key")

    database_path = file_values.get("BULLETFEED_DATABASE_PATH", "").replace("\\", "/")
    if database_path in {"", ".", "data/bulletfeed.db"}:
        errors.append("BULLETFEED_DATABASE_PATH must be an explicit release path")

    timeout_raw = file_values.get("BULLETFEED_REQUEST_TIMEOUT_SECONDS", "10")
    bytes_raw = file_values.get("BULLETFEED_MAX_RESPONSE_BYTES", "1048576")
    try:
        if float(timeout_raw) <= 0:
            errors.append("BULLETFEED_REQUEST_TIMEOUT_SECONDS must be positive")
    except ValueError:
        errors.append("BULLETFEED_REQUEST_TIMEOUT_SECONDS must be a number")
    try:
        if int(bytes_raw) <= 0:
            errors.append("BULLETFEED_MAX_RESPONSE_BYTES must be positive")
    except ValueError:
        errors.append("BULLETFEED_MAX_RESPONSE_BYTES must be a number")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        default=os.environ.get("BULLETFEED_RELEASE_ENV", ".env.release"),
        help="Release env file (never commit real secrets)",
    )
    args = parser.parse_args(argv)
    errors = validate_release_env(Path(args.env_file))
    if errors:
        for item in errors:
            print(f"release config invalid: {item}", file=sys.stderr)
        return 2
    print("release config valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
