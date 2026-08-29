from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.database import Database
from app.services.source_catalog import SourceKind, get_source_policy, source_allows_claim_evidence
from app.services.web_changes import (
    CHANGE_EXTRACTOR_VERSION,
    ChangeSetImmutabilityError,
    ChangeSetStore,
    classify_text_change,
    extract_web_changes,
    extract_web_snapshot_changes,
    generic_web_allows_claim_evidence,
    suppress_template_duplicates,
)
from app.services.web_normalize import (
    ALIGNER_VERSION,
    NormalizedDocumentStore,
    align_normalized_documents,
    normalize_web_snapshot,
)
from app.services.web_snapshots import (
    RobotsDecision,
    SnapshotStore,
    WebSnapshot,
    content_hash_for,
    snapshot_id_for,
)

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


def _page(
    *,
    nav: str = "Home · Docs · 2026-08-20",
    sections: list[tuple[str, str]],
    extra: str = "",
    footer: str = "Copyright 2026 Acme",
) -> bytes:
    blocks = "".join(f"<h2>{heading}</h2>{body}" for heading, body in sections)
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <title>Acme Widget docs</title>
    <style>.nav {{ color: red }}</style>
    <script>window.__boot = true;</script>
  </head>
  <body>
    <nav class="navbar">{nav}</nav>
    <header class="banner">Acme Widget</header>
    <main>
      {blocks}
      {extra}
    </main>
    <aside class="sidebar">Related links</aside>
    <footer>{footer}</footer>
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


def _section_by_heading(document, heading: str):
    matches = [section for section in document.sections if section.heading == heading]
    assert matches, f"missing section {heading!r}"
    return matches[0]


def _kinds(changeset) -> set[str]:
    return {item.change_kind for item in changeset.meaningful_candidates}


def test_generic_web_still_is_not_claim_evidence_after_change_extraction() -> None:
    policy = get_source_policy(SourceKind.GENERIC_WEB)
    assert policy.discovery_only is True
    assert source_allows_claim_evidence(SourceKind.GENERIC_WEB.value) is False
    assert generic_web_allows_claim_evidence() is False


def test_price_change_is_typed_update_with_spans_and_section_identity() -> None:
    first = _snapshot(_page(sections=V1_SECTIONS))
    updated = [
        V1_SECTIONS[0],
        (
            "Pricing",
            """
            <p>Monthly plans.</p>
            <table>
              <tr><th>Plan</th><th>Price</th></tr>
              <tr><td>Pro</td><td>$12</td></tr>
            </table>
            """,
        ),
    ]
    second = _snapshot(_page(sections=updated), retrieved_at="2026-08-30T00:00:00Z")
    changeset = extract_web_snapshot_changes(first, second)
    left_doc = normalize_web_snapshot(first)
    right_doc = normalize_web_snapshot(second)
    pricing_id = _section_by_heading(left_doc, "Pricing").section_id

    assert changeset.rejected is False
    assert changeset.extractor_version == CHANGE_EXTRACTOR_VERSION
    assert changeset.aligner_version == ALIGNER_VERSION
    prices = [item for item in changeset.candidates if item.change_kind == "price_limit_change"]
    assert len(prices) == 1
    candidate = prices[0]
    assert candidate.operation == "update"
    assert candidate.section_id == pricing_id
    assert candidate.left_section_id == candidate.right_section_id == pricing_id
    assert candidate.old_span is not None and candidate.new_span is not None
    assert "$10" in (candidate.old_value or candidate.old_span.text)
    assert "$12" in (candidate.new_value or candidate.new_span.text)
    assert candidate.old_span.locator.dom_path
    assert candidate.new_span.locator.dom_path
    assert candidate.confidence_label in {"high", "medium"}
    assert "price" in candidate.reason or "Price" in candidate.reason or candidate.old_value
    assert candidate.abstain_for_semantics is False
    assert _section_by_heading(left_doc, "Pricing").section_id == _section_by_heading(
        right_doc, "Pricing"
    ).section_id


def test_added_paragraph_is_insert_of_factual_block() -> None:
    first = _snapshot(_page(sections=V1_SECTIONS))
    second = _snapshot(
        _page(
            sections=[
                *V1_SECTIONS,
                ("Limits", "<p>Rate limit is 100 requests per minute.</p>"),
            ]
        ),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    changeset = extract_web_snapshot_changes(first, second)
    added = [
        item
        for item in changeset.candidates
        if item.operation == "insert" and item.change_kind != "non_meaningful"
    ]
    assert added
    limits = next(
        item
        for item in added
        if item.new_span and "100" in item.new_span.text
    )
    assert limits.change_kind in {"price_limit_change", "text_addition"}
    assert limits.old_span is None
    assert limits.new_span is not None
    assert limits.section_id == limits.right_section_id
    assert limits.left_section_id is None
    right = normalize_web_snapshot(second)
    assert limits.section_id == _section_by_heading(right, "Limits").section_id


def test_nav_only_change_is_ignored() -> None:
    first = _snapshot(_page(nav="Home · Docs · fetched 10:00", sections=V1_SECTIONS))
    second = _snapshot(
        _page(nav="Home · Docs · fetched 11:00 · ads", sections=V1_SECTIONS),
        retrieved_at="2026-08-29T01:00:00Z",
    )
    changeset = extract_web_snapshot_changes(first, second)
    assert changeset.meaningful_candidates == ()
    assert all(item.change_kind == "non_meaningful" for item in changeset.candidates)


def test_template_footer_noise_is_ignored() -> None:
    first = _snapshot(_page(sections=V1_SECTIONS))
    second = _snapshot(
        _page(sections=V1_SECTIONS, footer="Copyright 2026 Acme · cookies"),
        retrieved_at="2026-08-29T01:00:00Z",
    )
    changeset = extract_web_snapshot_changes(first, second)
    assert changeset.meaningful_candidates == ()


def test_api_limit_change_is_price_limit_change() -> None:
    first = _snapshot(
        _page(sections=[("Limits", "<p>Rate limit is 100 requests per minute.</p>")])
    )
    second = _snapshot(
        _page(sections=[("Limits", "<p>Rate limit is 1000 requests per minute.</p>")]),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    changeset = extract_web_snapshot_changes(first, second)
    assert "price_limit_change" in _kinds(changeset)
    candidate = next(item for item in changeset.candidates if item.change_kind == "price_limit_change")
    assert candidate.old_span is not None and candidate.new_span is not None
    assert "100" in candidate.old_span.text
    assert "1000" in candidate.new_span.text
    assert candidate.old_value != candidate.new_value


def test_version_change_is_never_normalized_away() -> None:
    first = _snapshot(_page(sections=[("Changelog", "<p>Widget 2.0 released.</p>")]))
    second = _snapshot(
        _page(sections=[("Changelog", "<p>Widget 2.1 released.</p>")]),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    changeset = extract_web_snapshot_changes(first, second)
    candidate = next(item for item in changeset.candidates if item.change_kind == "version_change")
    old_text = candidate.old_value or (candidate.old_span.text if candidate.old_span else "")
    new_text = candidate.new_value or (candidate.new_span.text if candidate.new_span else "")
    assert "2.0" in old_text
    assert "2.1" in new_text
    kind, _confidence, reason, old_value, new_value = classify_text_change(
        "Widget v2.0 released",
        "Widget 2.0 released",
    )
    assert kind == "non_meaningful"
    assert old_value is None and new_value is None
    assert "version" not in reason or kind == "non_meaningful"


def test_deprecation_date_change_preserves_raw_dates() -> None:
    first = _snapshot(
        _page(
            sections=[
                ("API", "<p>API v1 is deprecated on December 31, 2026.</p>"),
            ]
        )
    )
    second = _snapshot(
        _page(
            sections=[
                ("API", "<p>API v1 is deprecated on January 15, 2027.</p>"),
            ]
        ),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    changeset = extract_web_snapshot_changes(first, second)
    candidate = next(
        item for item in changeset.candidates if item.change_kind == "date_deadline_change"
    )
    assert "December 31, 2026" in (candidate.old_value or candidate.old_span.text)
    assert "January 15, 2027" in (candidate.new_value or candidate.new_span.text)
    same_day = classify_text_change(
        "Deprecated on December 31, 2026",
        "Deprecated on 2026-12-31",
    )
    assert same_day[0] == "non_meaningful"


def test_availability_change_is_status_availability() -> None:
    first = _snapshot(_page(sections=[("Plans", "<p>Pro plan is available.</p>")]))
    second = _snapshot(
        _page(sections=[("Plans", "<p>Pro plan is unavailable.</p>")]),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    changeset = extract_web_snapshot_changes(first, second)
    candidate = next(
        item for item in changeset.candidates if item.change_kind == "status_availability_change"
    )
    assert candidate.old_value == "available"
    assert candidate.new_value == "unavailable"
    equivalent = classify_text_change("Pro plan is not available.", "Pro plan is unavailable.")
    assert equivalent[0] == "non_meaningful"


def test_typo_only_is_non_meaningful() -> None:
    first = _snapshot(_page(sections=[("Changelog", "<p>Widget 2.0 released.</p>")]))
    second = _snapshot(
        _page(sections=[("Changelog", "<p>Widget 2.0 releasd.</p>")]),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    changeset = extract_web_snapshot_changes(first, second)
    assert changeset.meaningful_candidates == ()
    assert any(item.change_kind == "non_meaningful" for item in changeset.candidates)
    kind, _confidence, reason, _old, _new = classify_text_change(
        "Monthly plans.",
        "Monthly  plans.",
    )
    assert kind == "non_meaningful"
    assert "whitespace" in reason or "formatting" in reason


def test_negation_change_is_never_non_meaningful() -> None:
    kind, confidence, reason, _old, _new = classify_text_change(
        "TLS 1.3 is required.",
        "TLS 1.3 is not required.",
    )
    assert kind != "non_meaningful"
    assert "negation" in reason
    assert confidence >= 0.8


def test_numeric_format_only_is_non_meaningful_but_value_change_is_not() -> None:
    same = classify_text_change("The cap is 1,000 requests.", "The cap is 1000 requests.")
    assert same[0] == "non_meaningful"
    changed = classify_text_change("The cap is 1,000 requests.", "The cap is 2,000 requests.")
    assert changed[0] in {"numeric_change", "price_limit_change"}
    assert "1000" in (changed[3] or "") or "1,000" in (changed[3] or "")
    assert "2000" in (changed[4] or "") or "2,000" in (changed[4] or "")


def test_table_row_addition_without_price_is_table_list_row_change() -> None:
    first = _snapshot(
        _page(
            sections=[
                (
                    "Features",
                    """
                    <table>
                      <tr><th>Name</th><th>Note</th></tr>
                      <tr><td>SSO</td><td>Included</td></tr>
                    </table>
                    """,
                )
            ]
        )
    )
    second = _snapshot(
        _page(
            sections=[
                (
                    "Features",
                    """
                    <table>
                      <tr><th>Name</th><th>Note</th></tr>
                      <tr><td>SSO</td><td>Included</td></tr>
                      <tr><td>Audit log</td><td>Included</td></tr>
                    </table>
                    """,
                )
            ]
        ),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    changeset = extract_web_snapshot_changes(first, second)
    assert "table_list_row_change" in _kinds(changeset)


def test_link_target_change_keeps_visible_text() -> None:
    first = _snapshot(
        _page(sections=[("Docs", '<p>See the <a href="https://example.com/v1">API docs</a>.</p>')])
    )
    second = _snapshot(
        _page(sections=[("Docs", '<p>See the <a href="https://example.com/v2">API docs</a>.</p>')]),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    changeset = extract_web_snapshot_changes(first, second)
    links = [item for item in changeset.candidates if item.change_kind == "link_target_change"]
    assert links
    assert "v1" in (links[0].old_value or "")
    assert "v2" in (links[0].new_value or "")
    assert links[0].old_span is not None
    assert links[0].old_span.locator.dom_path
    assert links[0].old_span.locator.start_offset is not None
    raw = first.body.decode()
    region = raw[links[0].old_span.locator.start_offset :]
    assert "example.com/v1" in region


def test_near_duplicate_template_edits_are_suppressed_without_deleting_snapshots(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path / "snaps")
    cookie = "<p>We use cookies to improve your experience on this site.</p>"
    changesets = []
    bodies: list[bytes] = []
    for slug in ("alpha", "beta", "gamma"):
        url = f"https://docs.example.com/{slug}"
        before = _page(sections=[("Intro", "<p>Welcome to the product docs.</p>")])
        after = _page(
            sections=[("Intro", "<p>Welcome to the product docs.</p>")],
            extra=cookie,
        )
        left = store.put(_snapshot(before, url=url))
        right = store.put(
            _snapshot(after, url=url, retrieved_at="2026-08-30T00:00:00Z")
        )
        bodies.append(before)
        bodies.append(after)
        changesets.append(extract_web_snapshot_changes(left, right))

    unique_url = "https://docs.example.com/pricing"
    price_left = store.put(
        _snapshot(_page(sections=V1_SECTIONS), url=unique_url)
    )
    price_html = _page(
        sections=[
            V1_SECTIONS[0],
            (
                "Pricing",
                """
                <p>Monthly plans.</p>
                <table>
                  <tr><th>Plan</th><th>Price</th></tr>
                  <tr><td>Pro</td><td>$12</td></tr>
                </table>
                """,
            ),
        ]
    )
    price_right = store.put(
        _snapshot(price_html, url=unique_url, retrieved_at="2026-08-30T00:00:00Z")
    )
    changesets.append(extract_web_snapshot_changes(price_left, price_right))

    suppressed = suppress_template_duplicates(changesets)
    cookie_sets = suppressed[:3]
    price_set = suppressed[3]
    assert all(
        any(
            item.suppressed and item.suppress_reason == "near_duplicate_template_edit"
            for item in itemset.candidates
        )
        for itemset in cookie_sets
    )
    assert any(
        item.change_kind == "price_limit_change" and not item.suppressed
        for item in price_set.candidates
    )
    assert store.get(price_left.snapshot_id) is not None
    assert store.get(price_right.snapshot_id) is not None
    assert store.get(price_left.snapshot_id).body == _page(sections=V1_SECTIONS)
    on_disk = list((tmp_path / "snaps").glob("*/body.bin"))
    assert len(on_disk) >= 8
    assert {path.read_bytes() for path in on_disk} >= set(bodies)


def test_low_confidence_candidates_remain_available_for_abstention() -> None:
    first = _snapshot(_page(sections=[("Notes", "<p>The dashboard layout uses cards.</p>")]))
    second = _snapshot(
        _page(sections=[("Notes", "<p>Office hours moved to the basement kitchen.</p>")]),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    changeset = extract_web_snapshot_changes(first, second)
    low = [
        item
        for item in changeset.candidates
        if item.confidence_label == "low" or item.abstain_for_semantics
    ]
    assert low
    assert all(item in changeset.downstream_candidates for item in low)
    assert all(item.change_kind != "non_meaningful" for item in low)
    assert all(item.abstain_for_semantics for item in low)


def test_candidates_are_versioned_replayable_and_immutable(tmp_path: Path) -> None:
    first = _snapshot(_page(sections=V1_SECTIONS))
    updated = [
        V1_SECTIONS[0],
        (
            "Pricing",
            """
            <p>Monthly plans.</p>
            <table>
              <tr><th>Plan</th><th>Price</th></tr>
              <tr><td>Pro</td><td>$12</td></tr>
            </table>
            """,
        ),
    ]
    second = _snapshot(_page(sections=updated), retrieved_at="2026-08-30T00:00:00Z")
    once = extract_web_snapshot_changes(first, second)
    again = extract_web_snapshot_changes(first, second)
    assert once == again
    assert once.changeset_id == again.changeset_id
    assert once.extractor_version == CHANGE_EXTRACTOR_VERSION

    store = ChangeSetStore(tmp_path / "changes")
    stored = store.put(once)
    assert store.put(again).changeset_id == stored.changeset_id
    assert store.get(once.changeset_id) == once
    assert store.list_ids() == (once.changeset_id,)

    mutated = replace(once, canonical_url="https://docs.example.com/mutated")
    try:
        store.put(mutated)
    except ChangeSetImmutabilityError:
        pass
    else:
        raise AssertionError("changeset store must refuse mutation")
    assert store.get(once.changeset_id) == once


def test_raw_snapshot_and_normalized_store_are_never_mutated(tmp_path: Path) -> None:
    body = _page(sections=V1_SECTIONS)
    snapshot = _snapshot(body)
    snap_store = SnapshotStore(tmp_path / "snaps")
    stored = snap_store.put(snapshot)
    original = bytes(stored.body)
    document = normalize_web_snapshot(stored)
    NormalizedDocumentStore(tmp_path / "normalized").put(document)
    other = _snapshot(
        _page(
            sections=[
                V1_SECTIONS[0],
                (
                    "Pricing",
                    """
                    <p>Monthly plans.</p>
                    <table>
                      <tr><th>Plan</th><th>Price</th></tr>
                      <tr><td>Pro</td><td>$12</td></tr>
                    </table>
                    """,
                ),
            ]
        ),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    extract_web_snapshot_changes(stored, other)
    ChangeSetStore(tmp_path / "changes").put(extract_web_snapshot_changes(stored, other))

    assert stored.body == original == body
    assert snap_store.get(stored.snapshot_id).body == body
    assert (tmp_path / "snaps" / stored.snapshot_id / "body.bin").read_bytes() == body


def test_change_extraction_does_not_write_observations_or_claims(tmp_path: Path) -> None:
    database = Database(tmp_path / "changes.db")
    database.initialize()
    first = _snapshot(_page(sections=V1_SECTIONS))
    second = _snapshot(
        _page(
            sections=[
                *V1_SECTIONS,
                ("Limits", "<p>Rate limit is 100 requests per minute.</p>"),
            ]
        ),
        retrieved_at="2026-08-30T00:00:00Z",
    )
    extract_web_snapshot_changes(first, second)
    with database.connect() as connection:
        observations = connection.execute("SELECT COUNT(*) AS count FROM observations").fetchone()
        claims = connection.execute("SELECT COUNT(*) AS count FROM state_claims").fetchone()
    assert observations["count"] == 0
    assert claims["count"] == 0


def test_rejected_documents_fail_closed() -> None:
    empty = normalize_web_snapshot(_snapshot(b""))
    other = normalize_web_snapshot(_snapshot(_page(sections=V1_SECTIONS)))
    changeset = extract_web_changes(empty, other)
    assert changeset.rejected is True
    assert changeset.candidates == ()


def test_alignment_is_reused_when_provided() -> None:
    left = normalize_web_snapshot(_snapshot(_page(sections=V1_SECTIONS)))
    right = normalize_web_snapshot(
        _snapshot(
            _page(
                sections=[
                    *V1_SECTIONS,
                    ("Limits", "<p>Burst cap is 20 requests.</p>"),
                ]
            ),
            retrieved_at="2026-08-30T00:00:00Z",
        )
    )
    alignment = align_normalized_documents(left, right)
    changeset = extract_web_changes(left, right, alignment=alignment)
    assert any(item.operation == "insert" for item in changeset.meaningful_candidates)
