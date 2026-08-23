from __future__ import annotations

import sys
import tomllib
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    project_metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project = project_metadata["project"]
    python_requirement = SpecifierSet(project["requires-python"])
    python_version = ".".join(map(str, sys.version_info[:3]))
    if python_version not in python_requirement:
        raise SystemExit(
            f"Python {python_version} does not satisfy project requires-python {python_requirement}"
        )

    requirements = list(project.get("dependencies", []))
    requirements.extend(project.get("optional-dependencies", {}).get("dev", []))
    failures: list[str] = []
    for raw in requirements:
        requirement = Requirement(raw)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            installed = metadata.version(requirement.name)
        except metadata.PackageNotFoundError:
            failures.append(f"{requirement.name}: missing from locked environment")
            continue
        if requirement.specifier and installed not in requirement.specifier:
            failures.append(
                f"{requirement.name}: installed {installed} does not satisfy {requirement.specifier}"
            )
    if failures:
        raise SystemExit("Lock/project metadata mismatch:\n" + "\n".join(failures))


if __name__ == "__main__":
    main()
