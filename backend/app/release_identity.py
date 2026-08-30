"""Release / build identity for ops and #169 observability."""

from __future__ import annotations

import os
from functools import lru_cache

from app.services.knowledge_identity import KNOWLEDGE_IDENTITY_VERSION
from app.services.relation import RELATION_FEATURE_VERSION

RELEASE_CHECKLIST_VERSION = "release-checklist-v1"
API_VERSION = "0.1.0"


@lru_cache
def release_identity() -> dict[str, str]:
    """Stable public identity fields for health and smoke reports."""
    git_sha = (
        os.environ.get("BULLETFEED_GIT_SHA")
        or os.environ.get("GITHUB_SHA")
        or "unknown"
    )
    build_id = os.environ.get("BULLETFEED_BUILD_ID") or git_sha
    image_tag = os.environ.get("BULLETFEED_IMAGE_TAG") or "local"
    return {
        "apiVersion": API_VERSION,
        "gitSha": git_sha[:40],
        "buildId": build_id[:64],
        "imageTag": image_tag[:64],
        "releaseChecklistVersion": RELEASE_CHECKLIST_VERSION,
        "relationFeatureVersion": RELATION_FEATURE_VERSION,
        "knowledgeIdentityVersion": KNOWLEDGE_IDENTITY_VERSION,
    }
