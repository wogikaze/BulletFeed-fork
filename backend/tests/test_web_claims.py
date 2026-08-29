from __future__ import annotations

from pathlib import Path

from app.database import Database
from app.services.feed_projection import FeedProjector
from app.services.source_catalog import SourceKind, get_source_policy, source_allows_claim_evidence
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.services.source_registry import SourceRegistry
from app.services.web_changes import extract_web_snapshot_changes
from app.services.web_claims import (
    generic_web_allows_claim_evidence,
    ingest_web_changeset,
    official_web_family_allows_claim_evidence,
    resolve_web_claim_source_type,
)
from app.services.web_snapshots import RobotsDecision, WebSnapshot, content_hash_for, snapshot_id_for
from app.stores.claim_ledger_store import ClaimLedgerStore

PAGE_URL = "https://docs.example.com/changelog"


def _snapshot(
    body: bytes,
    *,
    url: str = PAGE_URL,
    retrieved_at: str = "2026-08-29T00:00:00Z",
) -> WebSnapshot:
    digest = content_hash_for(body)
    return WebSnapshot(
        snapshot_id=snapshot_id_for(canonical_url=url, content_hash=digest),
        canonical_url=url,
        retrieved_at=retrieved_at,
        content_hash=digest,
        status_code=200,
        headers=(("content-type", "text/html; charset=utf-8"),),
        body=body,
        etag='"v1"',
        last_modified="Wed, 20 Aug 2026 10:00:00 GMT",
        robots=RobotsDecision(
            source_url=url,
            robots_url="https://docs.example.com/robots.txt",
            allowed=True,
            reason="robots_missing",
            retrieved_at=retrieved_at,
        ),
        final_url=url,
    )


def _page(*, sections: list[tuple[str, str]], extra: str = "") -> bytes:
    blocks = "".join(f"<h2>{heading}</h2>{body}" for heading, body in sections)
    return f"""<!DOCTYPE html>
<html lang="en">
  <head><title>Acme Widget docs</title></head>
  <body>
    <nav class="navbar">Home · Docs</nav>
    <main>
      {blocks}
      {extra}
    </main>
    <footer>Copyright 2026 Acme</footer>
  </body>
</html>
""".encode()


V1_SECTIONS = [
    ("Changelog", "<p>Widget 2.0 released.</p>"),
    (
        "Pricing",
        """
        <p>Monthly plans.</p>
        <table>
          <tr><th>Plan</th><th>Price</th></tr>
          <tr><td>Pro</td><td>$10</td></tr>
        </table>
        """,
    ),
]


def _price_sections(price: str, note: str = "Monthly plans.") -> list[tuple[str, str]]:
    return [
        V1_SECTIONS[0],
        (
            "Pricing",
            f"""
            <p>{note}</p>
            <table>
              <tr><th>Plan</th><th>Price</th></tr>
              <tr><td>Pro</td><td>{price}</td></tr>
            </table>
            """,
        ),
    ]


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "web-claims.db")
    database.initialize()
    return database


def _allowlist(url: str = PAGE_URL, family: str = SourceKind.OFFICIAL_CHANGELOG.value) -> SourceRegistry:
    registry = SourceRegistry(seed_mvp=False)
    registry.register_publisher(slug="acme", display_name="Acme", homepage_url="https://docs.example.com")
    registry.register_endpoint(url=url, family=family, publisher_slug="acme")
    return registry


def test_generic_web_stays_discovery_only_and_cannot_back_claims() -> None:
    policy = get_source_policy(SourceKind.GENERIC_WEB)
    assert policy.discovery_only is True
    assert source_allows_claim_evidence(SourceKind.GENERIC_WEB.value) is False
    assert generic_web_allows_claim_evidence() is False
    assert official_web_family_allows_claim_evidence(SourceKind.GENERIC_WEB.value) is False
    assert official_web_family_allows_claim_evidence("random_html") is False
    assert official_web_family_allows_claim_evidence(SourceKind.OFFICIAL_CHANGELOG.value) is True
    assert official_web_family_allows_claim_evidence(SourceKind.DOCUMENTATION.value) is True


def test_discovery_only_generic_web_writes_observation_not_claim(tmp_path: Path) -> None:
    database = _database(tmp_path)
    first = _snapshot(_page(sections=V1_SECTIONS))
    second = _snapshot(
        _page(sections=_price_sections("$12")),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    changeset = extract_web_snapshot_changes(first, second)
    result = ingest_web_changeset(
        database,
        changeset,
        left_snapshot=first,
        right_snapshot=second,
    )

    assert result.source_type == SourceKind.GENERIC_WEB.value
    assert result.claim_eligible is False
    assert result.observations
    assert result.claims == ()
    assert result.event_ids == ()
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] >= 1
        assert connection.execute("SELECT COUNT(*) FROM state_claims").fetchone()[0] == 0
        source_types = {
            row["source_type"]
            for row in connection.execute("SELECT DISTINCT source_type FROM observations")
        }
        assert source_types == {SourceKind.GENERIC_WEB.value}
        payload = connection.execute("SELECT payload_json FROM observations LIMIT 1").fetchone()
        assert first.snapshot_id in payload["payload_json"] or second.snapshot_id in payload["payload_json"]


def test_unregistered_official_request_stays_generic_web(tmp_path: Path) -> None:
    database = _database(tmp_path)
    registry = SourceRegistry(seed_mvp=False)
    first = _snapshot(_page(sections=V1_SECTIONS))
    second = _snapshot(_page(sections=_price_sections("$12")), retrieved_at="2026-08-30T00:00:00Z")
    result = ingest_web_changeset(
        database,
        extract_web_snapshot_changes(first, second),
        left_snapshot=first,
        right_snapshot=second,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
    )
    assert resolve_web_claim_source_type(
        PAGE_URL,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
    ) == SourceKind.GENERIC_WEB.value
    assert result.source_type == SourceKind.GENERIC_WEB.value
    assert result.claims == ()


def test_official_allowlisted_page_produces_claim_and_evidence(tmp_path: Path) -> None:
    database = _database(tmp_path)
    registry = _allowlist()
    first = _snapshot(_page(sections=V1_SECTIONS))
    second = _snapshot(_page(sections=_price_sections("$12")), retrieved_at="2026-08-30T00:00:00Z")
    changeset = extract_web_snapshot_changes(first, second)
    result = ingest_web_changeset(
        database,
        changeset,
        left_snapshot=first,
        right_snapshot=second,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
    )

    assert result.source_type == SourceKind.OFFICIAL_CHANGELOG.value
    assert result.claim_eligible is True
    prices = [claim for claim in result.claims if claim.slot in {"price", "limit"}]
    assert prices
    claim = prices[0]
    assert "$12" in claim.value or "12" in claim.value
    assert "$10" in claim.detail and "$12" in claim.detail
    with database.connect() as connection:
        evidence = connection.execute(
            """
            SELECT e.*, o.source_type, o.payload_json
            FROM claim_evidence e
            JOIN observations o ON o.id = e.observation_id
            WHERE e.claim_id = ?
            """,
            (claim.claim_id,),
        ).fetchone()
    assert evidence is not None
    assert evidence["source_type"] == SourceKind.OFFICIAL_CHANGELOG.value
    assert first.snapshot_id in evidence["payload_json"]
    assert second.snapshot_id in evidence["payload_json"]
    assert first.snapshot_id in evidence["evidence_text"] or "snapshot=" in evidence["evidence_text"]
    assert second.snapshot_id in evidence["evidence_text"]
    assert "section=" in evidence["evidence_text"]
    assert "$10" in evidence["evidence_text"] or "$10" in evidence["payload_json"]
    assert "$12" in evidence["evidence_text"] or "$12" in evidence["payload_json"]
    assert evidence["original_url"] == PAGE_URL


def test_documentation_allowlist_can_produce_claim(tmp_path: Path) -> None:
    database = _database(tmp_path)
    registry = _allowlist(family=SourceKind.DOCUMENTATION.value)
    first = _snapshot(_page(sections=[("Limits", "<p>Rate limit is 100 requests per minute.</p>")]))
    second = _snapshot(
        _page(sections=[("Limits", "<p>Rate limit is 1000 requests per minute.</p>")]),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    result = ingest_web_changeset(
        database,
        extract_web_snapshot_changes(first, second),
        left_snapshot=first,
        right_snapshot=second,
        registry=registry,
    )
    assert result.source_type == SourceKind.DOCUMENTATION.value
    assert any(claim.slot in {"limit", "price", "quota"} for claim in result.claims)
    assert "100" in (result.claims[0].detail + result.claims[0].value)
    assert "1000" in (result.claims[0].detail + result.claims[0].value)


def test_ingest_is_idempotent(tmp_path: Path) -> None:
    database = _database(tmp_path)
    registry = _allowlist()
    first = _snapshot(_page(sections=V1_SECTIONS))
    second = _snapshot(_page(sections=_price_sections("$12")), retrieved_at="2026-08-30T00:00:00Z")
    changeset = extract_web_snapshot_changes(first, second)
    once = ingest_web_changeset(
        database,
        changeset,
        left_snapshot=first,
        right_snapshot=second,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
    )
    again = ingest_web_changeset(
        database,
        changeset,
        left_snapshot=first,
        right_snapshot=second,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
    )
    assert [claim.claim_id for claim in again.claims] == [claim.claim_id for claim in once.claims]
    assert [item.id for item in again.observations] == [item.id for item in once.observations]
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == len(once.observations)
        assert connection.execute("SELECT COUNT(*) FROM state_claims").fetchone()[0] == len(once.claims)
        assert connection.execute("SELECT COUNT(*) FROM claim_evidence").fetchone()[0] == len(once.claims)


def test_same_page_repeated_changes_preserve_history(tmp_path: Path) -> None:
    database = _database(tmp_path)
    registry = _allowlist()
    v1 = _snapshot(_page(sections=V1_SECTIONS))
    v2 = _snapshot(_page(sections=_price_sections("$12")), retrieved_at="2026-08-30T00:00:00Z")
    v3 = _snapshot(_page(sections=_price_sections("$15")), retrieved_at="2026-08-31T00:00:00Z")
    first = ingest_web_changeset(
        database,
        extract_web_snapshot_changes(v1, v2),
        left_snapshot=v1,
        right_snapshot=v2,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
    )
    second = ingest_web_changeset(
        database,
        extract_web_snapshot_changes(v2, v3),
        left_snapshot=v2,
        right_snapshot=v3,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
    )
    first_price = next(claim for claim in first.claims if claim.slot in {"price", "limit"})
    second_price = next(claim for claim in second.claims if claim.slot in {"price", "limit"})
    assert first_price.event_id == second_price.event_id
    assert first_price.claim_id != second_price.claim_id
    assert second_price.relation_type in {"STATE_UPDATE", "CORRECTION"}
    assert "$15" in second_price.value or "15" in second_price.value
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT value_text, valid_at FROM state_claims WHERE event_id = ? AND slot = ? ORDER BY valid_at",
            (first_price.event_id, first_price.slot),
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["valid_at"] < rows[1]["valid_at"]


def test_added_detail_uses_existing_revision_judge(tmp_path: Path) -> None:
    database = _database(tmp_path)
    registry = _allowlist()
    empty = _snapshot(_page(sections=[("Changelog", "<p>Coming soon.</p>")]))
    first = _snapshot(
        _page(sections=[("Changelog", "<p>Widget 2.0 released.</p>")]),
        retrieved_at="2026-08-29T12:00:00Z",
    )
    second = _snapshot(
        _page(
            sections=[
                (
                    "Changelog",
                    "<p>Widget 2.0 released.</p><p>Widget 2.0 also includes SSO.</p>",
                )
            ]
        ),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    initial = ingest_web_changeset(
        database,
        extract_web_snapshot_changes(empty, first),
        left_snapshot=empty,
        right_snapshot=first,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
    )
    detail = ingest_web_changeset(
        database,
        extract_web_snapshot_changes(first, second),
        left_snapshot=first,
        right_snapshot=second,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
    )
    first_version = next(claim for claim in initial.claims if claim.slot == "version")
    second_version = next(claim for claim in detail.claims if claim.slot == "version")
    assert first_version.event_id == second_version.event_id
    assert first_version.value == second_version.value
    assert second_version.relation_type == "DETAIL"
    assert "SSO" in second_version.detail


def test_ambiguous_prose_is_observation_only(tmp_path: Path) -> None:
    database = _database(tmp_path)
    registry = _allowlist()
    first = _snapshot(_page(sections=[("Notes", "<p>The dashboard layout uses cards.</p>")]))
    second = _snapshot(
        _page(sections=[("Notes", "<p>Office hours moved to the basement kitchen.</p>")]),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    changeset = extract_web_snapshot_changes(first, second)
    assert any(item.abstain_for_semantics for item in changeset.downstream_candidates)
    result = ingest_web_changeset(
        database,
        changeset,
        left_snapshot=first,
        right_snapshot=second,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
    )
    assert result.observations
    assert result.claims == ()
    assert result.abstained_candidate_ids


def test_correction_is_history_preserving(tmp_path: Path) -> None:
    database = _database(tmp_path)
    registry = _allowlist()
    first = _snapshot(_page(sections=_price_sections("$12")))
    second = _snapshot(
        _page(
            sections=_price_sections("$10 (corrected)", note="Monthly plans."),
        ),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    initial = ingest_web_changeset(
        database,
        extract_web_snapshot_changes(_snapshot(_page(sections=V1_SECTIONS)), first),
        left_snapshot=_snapshot(_page(sections=V1_SECTIONS)),
        right_snapshot=first,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
        retrieved_at="2026-08-29T00:00:00Z",
    )
    corrected = ingest_web_changeset(
        database,
        extract_web_snapshot_changes(first, second),
        left_snapshot=first,
        right_snapshot=second,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
    )
    first_price = next(claim for claim in initial.claims if claim.slot in {"price", "limit"})
    second_price = next(claim for claim in corrected.claims if claim.slot in {"price", "limit"})
    assert first_price.event_id == second_price.event_id
    assert second_price.relation_type == "CORRECTION"
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM state_claims WHERE event_id = ? AND slot = ?",
            (first_price.event_id, first_price.slot),
        ).fetchone()[0] == 2


def test_cross_source_same_event_uses_existing_coreference(tmp_path: Path) -> None:
    database = _database(tmp_path)
    registry = _allowlist()
    release = SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type="github_release",
                source_key="acme/widget",
                source_observation_id="release:42",
                payload={"id": 42, "tag_name": "v2.0.0"},
                original_url="https://github.com/acme/widget/releases/tag/v2.0.0",
                published_at="2026-08-29T00:00:00Z",
            ),
        ),
        retrieved_at="2026-08-29T00:01:00Z",
    )[0]
    prior = ClaimLedgerStore(database).ingest(
        release,
        source_event_id="release:42",
        title="Widget 2.0 released",
        slot="version",
        value="2.0",
        detail="Widget 2.0 released",
        valid_at="2026-08-29T00:00:00Z",
        evidence_text="Widget 2.0 released",
        coreference_subject="Widget 2.0 released",
    )
    first = _snapshot(_page(sections=[("Changelog", "<p>Coming soon.</p>")]))
    second = _snapshot(
        _page(sections=[("Changelog", "<p>Widget 2.0 released.</p>")]),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    result = ingest_web_changeset(
        database,
        extract_web_snapshot_changes(first, second),
        left_snapshot=first,
        right_snapshot=second,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
        coreference_subject="Widget 2.0 released",
        event_title="Widget 2.0 released",
        project=False,
    )
    assert result.claims
    assert any(claim.event_id == prior.event_id for claim in result.claims)


def test_successful_ingest_projects_public_event_and_user_feed(tmp_path: Path) -> None:
    database = _database(tmp_path)
    registry = _allowlist()
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")
    first = _snapshot(_page(sections=V1_SECTIONS))
    second = _snapshot(_page(sections=_price_sections("$12")), retrieved_at="2026-08-30T00:00:00Z")
    result = ingest_web_changeset(
        database,
        extract_web_snapshot_changes(first, second),
        left_snapshot=first,
        right_snapshot=second,
        registry=registry,
        requested_family=SourceKind.OFFICIAL_CHANGELOG.value,
        audience_user_ids=("user_1",),
    )
    assert result.event_ids
    event_id = result.event_ids[0]
    with database.connect() as connection:
        event = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        delta = connection.execute("SELECT * FROM deltas WHERE event_id = ?", (event_id,)).fetchone()
        source = connection.execute(
            "SELECT * FROM event_sources WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    assert event is not None
    assert delta is not None
    assert source is not None
    assert source["kind"] == SourceKind.OFFICIAL_CHANGELOG.value
    assert source["url"] == PAGE_URL
    assert second.snapshot_id in source["evidence"] or "snapshot=" in source["evidence"]
    feed_ids = FeedProjector(database).project_event_for_user(user_id="user_1", event_id=event_id)
    assert feed_ids
    with database.connect() as connection:
        items = connection.execute(
            "SELECT * FROM feed_items WHERE user_id = 'user_1' AND event_id = ?",
            (event_id,),
        ).fetchall()
    assert items
