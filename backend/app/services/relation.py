from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.event_concepts import RelationConceptFeatures


@dataclass(frozen=True)
class RelationSignal:
    level: str
    reason: str
    matched_topics: tuple[str, ...]
    matched_repositories: tuple[dict[str, str], ...]
    personalization_rank: int = 0


def evaluate_relation(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    source_type: str,
    source_key: str,
    event_title: str,
    event_summary: str,
) -> RelationSignal:
    repo = _selected_repository(connection, user_id=user_id, source_key=source_key)
    if repo is not None and source_type in {
        "github_release",
        "github_sbom",
        "osv",
        "github_advisory",
    }:
        return RelationSignal(
            level="direct",
            reason="Directly matches a selected GitHub repository.",
            matched_topics=(),
            matched_repositories=(repo,),
            personalization_rank=1000,
        )

    text = " ".join((source_key, event_title, event_summary))
    matched_topics, topic_rank = _matched_topics(
        connection,
        user_id=user_id,
        text=text,
    )
    if matched_topics:
        return RelationSignal(
            level="adjacent",
            reason="Matches one or more topics you follow.",
            matched_topics=matched_topics,
            matched_repositories=(),
            personalization_rank=topic_rank,
        )

    profile_matches = _matched_profile_terms(connection, user_id=user_id, text=text)
    if profile_matches:
        return RelationSignal(
            level="adjacent",
            reason="Matches your profile or interests.",
            matched_topics=profile_matches,
            matched_repositories=(),
            personalization_rank=75,
        )

    return RelationSignal(
        level="reference",
        reason="",
        matched_topics=(),
        matched_repositories=(),
        personalization_rank=0,
    )


def _selected_repository(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    source_key: str,
) -> dict[str, str] | None:
    if not source_key:
        return None
    row = connection.execute(
        """
        SELECT repository_id, full_name, html_url
        FROM github_repo_watches
        WHERE user_id = ? AND full_name = ? AND selected = 1
        LIMIT 1
        """,
        (user_id, source_key),
    ).fetchone()
    if row is None:
        return None
    full_name = row["full_name"]
    return {
        "id": row["repository_id"],
        "name": full_name,
        "url": row["html_url"] or f"https://github.com/{full_name}",
    }


def _matched_topics(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    text: str,
) -> tuple[tuple[str, ...], int]:
    normalized_text = _normalize(text)
    if not normalized_text:
        return (), 0
    rows = connection.execute(
        """
        SELECT name, priority, sort_order
        FROM topics
        WHERE user_id = ?
        ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                 sort_order,
                 name
        """,
        (user_id,),
    ).fetchall()
    matched: list[str] = []
    best_rank = 0
    padded_text = f" {normalized_text} "
    priority_base = {"high": 300, "normal": 200, "low": 100}
    for row in rows:
        topic = row["name"].strip()
        normalized_topic = _normalize(topic)
        if normalized_topic and f" {normalized_topic} " in padded_text:
            matched.append(topic)
            order_bonus = max(0, 99 - min(int(row["sort_order"]), 99))
            best_rank = max(best_rank, priority_base.get(row["priority"], 100) + order_bonus)
    return tuple(matched), best_rank


def _matched_profile_terms(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    text: str,
) -> tuple[str, ...]:
    normalized_text = f" {_normalize(text)} "
    if normalized_text == "  ":
        return ()
    row = connection.execute(
        "SELECT occupation, interests_json FROM profiles WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return ()
    terms: list[str] = []
    if row["occupation"]:
        terms.append(row["occupation"])
    try:
        interests = json.loads(row["interests_json"])
    except (TypeError, ValueError):
        interests = []
    if isinstance(interests, list):
        terms.extend(str(item) for item in interests if isinstance(item, str))
    matches: list[str] = []
    for term in terms:
        normalized_term = _normalize(term)
        if normalized_term and f" {normalized_term} " in normalized_text:
            matches.append(term)
    return tuple(dict.fromkeys(matches))


def consume_concept_features(
    features: RelationConceptFeatures | Mapping[str, Any],
) -> tuple[str, ...]:
    """Return match terms from Event concepts without reparsing raw Event prose.

    This is a consumer helper for later semantic Relation work. It does not
    change evaluate_relation scoring or reasons.
    """
    payload = features.to_snapshot() if isinstance(features, RelationConceptFeatures) else dict(features)
    terms: list[str] = []
    for key in ("canonical_names", "stable_ids", "concept_ids", "aliases"):
        values = payload.get(key) or ()
        for value in values:
            if isinstance(value, str) and value.strip():
                terms.append(value)
    return tuple(dict.fromkeys(terms))


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).split())
