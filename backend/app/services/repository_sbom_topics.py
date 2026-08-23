from __future__ import annotations

from fastapi import HTTPException

from app.config import Settings
from app.services.github_sbom_source import fetch_github_sbom

_MAX_SBOM_PACKAGES = 500


async def sbom_topic_signal_text(
    settings: Settings,
    *,
    owner: str,
    repository: str,
    token: str,
) -> str:
    """Return bounded package/PURL text for topic inference.

    Dependency Graph is optional on GitHub. Failure to obtain an SBOM must not
    make repository selection fail, because manifests and language metadata are
    still useful inference sources.
    """
    try:
        payload = await fetch_github_sbom(
            settings,
            owner=owner,
            repository=repository,
            token=token,
        )
    except HTTPException:
        return ""

    sbom = payload.get("sbom")
    if not isinstance(sbom, dict):
        return ""
    packages = sbom.get("packages")
    if not isinstance(packages, list):
        return ""

    signals: list[str] = []
    for package in packages[:_MAX_SBOM_PACKAGES]:
        if not isinstance(package, dict):
            continue
        name = package.get("name")
        if isinstance(name, str) and name:
            signals.append(name)
        refs = package.get("externalRefs")
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            locator = ref.get("referenceLocator")
            if isinstance(locator, str) and locator:
                signals.append(locator)
    return "\n".join(signals)
