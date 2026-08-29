"""One-command release stack start: validate config, then compose up."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validate_release_config import validate_release_env  # noqa: E402


def start_release_stack(
    *,
    env_file: Path,
    compose_file: Path,
    validate_only: bool = False,
) -> int:
    errors = validate_release_env(env_file)
    if errors:
        for item in errors:
            print(f"release config invalid: {item}", file=sys.stderr)
        return 2
    print("release config valid")
    if validate_only:
        return 0
    command = (
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "--env-file",
        str(env_file),
        "up",
        "-d",
        "--build",
    )
    print(" ".join(command))
    completed = subprocess.run(command, check=False)  # noqa: S603
    return int(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env.release")
    parser.add_argument("--compose-file", default="compose.release.yml")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate configuration without starting Docker",
    )
    args = parser.parse_args(argv)
    backend_root = Path(__file__).resolve().parents[1]
    env_file = Path(args.env_file)
    compose_file = Path(args.compose_file)
    if not env_file.is_absolute():
        env_file = backend_root / env_file
    if not compose_file.is_absolute():
        compose_file = backend_root / compose_file
    os.chdir(backend_root)
    return start_release_stack(
        env_file=env_file,
        compose_file=compose_file,
        validate_only=args.validate_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
