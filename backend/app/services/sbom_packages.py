from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote


@dataclass(frozen=True)
class OsvPackage:
    ecosystem: str
    name: str
    version: str
    purl: str


_PURL_ECOSYSTEMS = {
    "cargo": "crates.io",
    "composer": "Packagist",
    "gem": "RubyGems",
    "golang": "Go",
    "maven": "Maven",
    "npm": "npm",
    "nuget": "NuGet",
    "pypi": "PyPI",
}


def extract_osv_packages(sbom_response: dict[str, Any]) -> tuple[OsvPackage, ...]:
    sbom = sbom_response.get("sbom")
    if not isinstance(sbom, dict):
        return ()
    packages = sbom.get("packages")
    if not isinstance(packages, list):
        return ()

    found: dict[tuple[str, str, str], OsvPackage] = {}
    for package in packages:
        if not isinstance(package, dict):
            continue
        refs = package.get("externalRefs")
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            locator = ref.get("referenceLocator")
            ref_type = ref.get("referenceType")
            if not isinstance(locator, str) or not locator.startswith("pkg:"):
                continue
            if isinstance(ref_type, str) and ref_type.lower() not in {"purl", "package-url"}:
                continue
            parsed = parse_purl(locator)
            if parsed is not None:
                found[(parsed.ecosystem, parsed.name, parsed.version)] = parsed
    return tuple(found[key] for key in sorted(found))


def parse_purl(purl: str) -> OsvPackage | None:
    if not purl.startswith("pkg:"):
        return None
    core = purl[4:].split("#", 1)[0].split("?", 1)[0]
    if "/" not in core or "@" not in core:
        return None
    package_type, rest = core.split("/", 1)
    path, version = rest.rsplit("@", 1)
    ecosystem = _PURL_ECOSYSTEMS.get(package_type.lower())
    if ecosystem is None or not version:
        return None

    parts = [unquote(part) for part in path.split("/") if part]
    if not parts:
        return None
    namespace = parts[:-1]
    leaf = parts[-1]
    if package_type.lower() == "maven" and namespace:
        name = f"{'.'.join(namespace)}:{leaf}"
    elif namespace:
        name = "/".join([*namespace, leaf])
    else:
        name = leaf
    return OsvPackage(
        ecosystem=ecosystem,
        name=name,
        version=unquote(version),
        purl=purl,
    )
