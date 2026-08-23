from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class FeedLifecycle:
    canonical_event_key: str
    subject: str
    slot: str
    state: str


_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^(?P<subject>.+?)\s+is being fully retired on\b", re.IGNORECASE),
        "retirement_announced",
    ),
    (
        re.compile(r"^(?P<subject>.+?)\s+will be retired on\b", re.IGNORECASE),
        "retirement_announced",
    ),
    (
        re.compile(r"^(?P<subject>.+?)\s+is now retired\b", re.IGNORECASE),
        "retired",
    ),
    (
        re.compile(r"^upcoming deprecation of\s+(?P<subject>.+?)(?:\s+on\b|$)", re.IGNORECASE),
        "deprecation_announced",
    ),
    (
        re.compile(r"^(?P<subject>.+?)\s+(?:is|are) now deprecated\b", re.IGNORECASE),
        "deprecated",
    ),
    (
        re.compile(r"^(?P<subject>.+?)\s+(?:is|are) deprecated\b", re.IGNORECASE),
        "deprecated",
    ),
)


def resolve_feed_lifecycle(title: str, original_url: str) -> FeedLifecycle | None:
    """Resolve only explicit lifecycle language; otherwise prefer a false split.

    Generic feed articles remain URL-scoped. We only coreference cross-article state
    transitions when the publisher itself uses unambiguous retirement/deprecation
    wording and the normalized subject is identical.
    """
    normalized_title = " ".join(title.split())
    hostname = (urlparse(original_url).hostname or "").lower().rstrip(".")
    if not normalized_title or not hostname:
        return None

    for pattern, state in _PATTERNS:
        match = pattern.search(normalized_title)
        if match is None:
            continue
        subject = match.group("subject").strip(" .:-")
        subject_key = _subject_key(subject)
        if not subject_key:
            return None
        return FeedLifecycle(
            canonical_event_key=f"feed-lifecycle:{hostname}:{subject_key}",
            subject=subject,
            slot="lifecycle_state",
            state=state,
        )
    return None


def _subject_key(subject: str) -> str:
    value = subject.casefold().replace("’", "'")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value
