from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.database import Database
from app.services.source_catalog import SourceKind, get_source_policy, source_allows_claim_evidence
from app.services.web_normalize import (
    ALIGNER_VERSION,
    NORMALIZER_VERSION,
    NormalizedDocumentImmutabilityError,
    NormalizedDocumentStore,
    WebNormalizationError,
    align_normalized_documents,
    generic_web_allows_claim_evidence,
    normalize_web_snapshot,
    require_normalized_document,
    section_id_for,
)
from app.services.web_snapshots import (
    RobotsDecision,
    SnapshotStore,
    WebSnapshot,
    content_hash_for,
    snapshot_id_for,
)

PAGE_URL = "https://docs.example.com/changelog"


def _snapshot(body: bytes, *, retrieved_at: str = "2026-08-29T00:00:00Z") -> WebSnapshot:
    digest = content_hash_for(body)
    return WebSnapshot(
        snapshot_id=snapshot_id_for(canonical_url=PAGE_URL, content_hash=digest),
        canonical_url=PAGE_URL,
        retrieved_at=retrieved_at,
        content_hash=digest,
        status_code=200,
        headers=(("content-type", "text/html; charset=utf-8"),),
        body=body,
        etag='"v1"',
        last_modified="Wed, 20 Aug 2026 10:00:00 GMT",
        robots=RobotsDecision(
            source_url=PAGE_URL,
            robots_url="https://docs.example.com/robots.txt",
            allowed=True,
            reason="robots_missing",
            retrieved_at=retrieved_at,
        ),
        final_url=PAGE_URL,
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
    assert matches, f"missing section {heading!r} in {[item.heading for item in document.sections]}"
    return matches[0]


def test_generic_web_still_is_not_claim_evidence_after_normalization() -> None:
    policy = get_source_policy(SourceKind.GENERIC_WEB)
    assert policy.discovery_only is True
    assert policy.authoritative is False
    assert source_allows_claim_evidence(SourceKind.GENERIC_WEB.value) is False
    assert generic_web_allows_claim_evidence() is False


def test_two_page_versions_keep_heading_ids_and_add_new_section() -> None:
    first = normalize_web_snapshot(_snapshot(_page(sections=V1_SECTIONS)))
    second_html = _page(
        nav="Home · Docs · 2026-08-29",
        sections=[
            *V1_SECTIONS,
            ("Limits", "<p>Rate limit is 100 requests per minute.</p>"),
        ],
    )
    second = normalize_web_snapshot(_snapshot(second_html, retrieved_at="2026-08-30T00:00:00Z"))

    assert first.rejected is False
    assert second.rejected is False
    assert first.normalizer_version == second.normalizer_version == NORMALIZER_VERSION
    changelog_v1 = _section_by_heading(first, "Changelog")
    pricing_v1 = _section_by_heading(first, "Pricing")
    changelog_v2 = _section_by_heading(second, "Changelog")
    pricing_v2 = _section_by_heading(second, "Pricing")
    limits_v2 = _section_by_heading(second, "Limits")

    assert changelog_v1.section_id == changelog_v2.section_id
    assert pricing_v1.section_id == pricing_v2.section_id
    assert limits_v2.section_id not in first.section_ids
    assert limits_v2.section_id == section_id_for(
        canonical_url=PAGE_URL,
        heading="Limits",
        heading_level=2,
        heading_path=("limits",),
    )

    alignment = align_normalized_documents(first, second)
    assert alignment.aligner_version == ALIGNER_VERSION
    by_right = {pair.right_section_id: pair for pair in alignment.pairs if pair.right_section_id}
    assert by_right[changelog_v2.section_id].status == "matched"
    assert by_right[pricing_v2.section_id].status == "matched"
    assert by_right[limits_v2.section_id].status == "inserted"
    assert by_right[limits_v2.section_id].left_section_id is None


def test_template_noise_does_not_change_section_identity() -> None:
    first = normalize_web_snapshot(
        _snapshot(_page(nav="Home · Docs · fetched 10:00", sections=V1_SECTIONS))
    )
    second = normalize_web_snapshot(
        _snapshot(
            _page(
                nav="Home · Docs · fetched 11:00 · ads",
                sections=V1_SECTIONS,
                footer="Copyright 2026 Acme · cookies",
            ),
            retrieved_at="2026-08-29T01:00:00Z",
        )
    )
    assert [section.heading for section in first.sections] == [
        section.heading for section in second.sections
    ]
    assert first.section_ids == second.section_ids
    texts = {
        (section.heading, tuple(block.text for block in section.blocks if block.kind != "heading"))
        for section in first.sections
    }
    again = {
        (section.heading, tuple(block.text for block in section.blocks if block.kind != "heading"))
        for section in second.sections
    }
    assert texts == again
    joined = " ".join(block.text for section in first.sections for block in section.blocks)
    assert "Home · Docs" not in joined
    assert "Copyright 2026" not in joined
    assert "Related links" not in joined
    assert "window.__boot" not in joined


def test_reordered_sections_keep_ids_and_record_reorder() -> None:
    first = normalize_web_snapshot(_snapshot(_page(sections=V1_SECTIONS)))
    second = normalize_web_snapshot(
        _snapshot(_page(sections=list(reversed(V1_SECTIONS))), retrieved_at="2026-08-30T00:00:00Z")
    )
    assert set(first.section_ids) == set(second.section_ids)
    assert [section.heading for section in first.sections] == ["Changelog", "Pricing"]
    assert [section.heading for section in second.sections] == ["Pricing", "Changelog"]
    statuses = {pair.status for pair in align_normalized_documents(first, second).pairs}
    assert statuses == {"reordered"}


def test_table_row_change_keeps_section_and_table_identity() -> None:
    first = normalize_web_snapshot(_snapshot(_page(sections=V1_SECTIONS)))
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
    second = normalize_web_snapshot(
        _snapshot(_page(sections=updated), retrieved_at="2026-08-30T00:00:00Z")
    )
    pricing_v1 = _section_by_heading(first, "Pricing")
    pricing_v2 = _section_by_heading(second, "Pricing")
    assert pricing_v1.section_id == pricing_v2.section_id
    table_v1 = next(block for block in pricing_v1.blocks if block.kind == "table")
    table_v2 = next(block for block in pricing_v2.blocks if block.kind == "table")
    assert table_v1.block_id == table_v2.block_id
    assert table_v1.local_key == table_v2.local_key == "table:0"
    assert "$10" in table_v1.text
    assert "$12" in table_v2.text
    pair = next(
        item
        for item in align_normalized_documents(first, second).pairs
        if item.left_section_id == pricing_v1.section_id
    )
    assert pair.status == "matched"


def test_heading_rename_is_uncertain_not_merged_as_same_section() -> None:
    first = normalize_web_snapshot(_snapshot(_page(sections=V1_SECTIONS)))
    renamed = [
        V1_SECTIONS[0],
        (
            "Plans and pricing",
            """
            <p>Monthly plans.</p>
            <table>
              <tr><th>Plan</th><th>Price</th></tr>
              <tr><td>Pro</td><td>$10</td></tr>
            </table>
            """,
        ),
    ]
    second = normalize_web_snapshot(
        _snapshot(_page(sections=renamed), retrieved_at="2026-08-30T00:00:00Z")
    )
    pricing = _section_by_heading(first, "Pricing")
    plans = _section_by_heading(second, "Plans and pricing")
    assert pricing.section_id != plans.section_id
    alignment = align_normalized_documents(first, second)
    rename = next(
        pair
        for pair in alignment.pairs
        if pair.left_section_id == pricing.section_id
    )
    assert rename.status == "uncertain"
    assert rename.right_section_id == plans.section_id
    assert 0.72 <= rename.confidence <= 1.0


def test_unrelated_leftover_sections_are_split_not_merged() -> None:
    first = normalize_web_snapshot(
        _snapshot(_page(sections=[("Security", "<p>TLS 1.3 is required.</p>")]))
    )
    second = normalize_web_snapshot(
        _snapshot(
            _page(sections=[("Pricing", "<p>Monthly plans start at $10.</p>")]),
            retrieved_at="2026-08-30T00:00:00Z",
        )
    )
    alignment = align_normalized_documents(first, second)
    statuses = {pair.status for pair in alignment.pairs}
    assert statuses == {"deleted", "inserted"}
    assert all(pair.status != "matched" for pair in alignment.pairs)
    assert all(pair.status != "uncertain" for pair in alignment.pairs)


def test_empty_and_garbage_html_fail_closed() -> None:
    empty = normalize_web_snapshot(_snapshot(b""))
    comments = normalize_web_snapshot(_snapshot(b"<!-- nothing -->"))
    script_only = normalize_web_snapshot(
        _snapshot(b"<html><body><div id='app'></div><script>boot()</script></body></html>")
    )
    nav_only = normalize_web_snapshot(
        _snapshot(b"<html><body><nav>Home About</nav><footer>c</footer></body></html>")
    )
    binary = normalize_web_snapshot(_snapshot(b"\x00\x01\xff\xfe" + b"\x00" * 64))
    for document in (empty, comments, script_only, nav_only, binary):
        assert document.rejected is True
        assert document.sections == ()
        assert document.normalizer_version == NORMALIZER_VERSION
        try:
            require_normalized_document(document)
        except WebNormalizationError:
            pass
        else:
            raise AssertionError("rejected document must fail closed")


def test_raw_snapshot_bytes_and_store_are_never_mutated(tmp_path: Path) -> None:
    body = _page(sections=V1_SECTIONS)
    snapshot = _snapshot(body)
    store = SnapshotStore(tmp_path / "snaps")
    stored = store.put(snapshot)
    original = bytes(stored.body)
    body_path = tmp_path / "snaps" / stored.snapshot_id / "body.bin"
    on_disk = body_path.read_bytes()

    document = normalize_web_snapshot(stored)
    NormalizedDocumentStore(tmp_path / "normalized").put(document)

    assert stored.body == original == on_disk == body
    assert store.get(stored.snapshot_id) is not None
    assert store.get(stored.snapshot_id).body == body
    assert (tmp_path / "snaps" / stored.snapshot_id / "body.bin").read_bytes() == body
    assert document.content_hash == stored.content_hash
    assert document.snapshot_id == stored.snapshot_id


def test_locators_trace_back_to_raw_snapshot_offsets() -> None:
    body = _page(sections=V1_SECTIONS)
    raw = body.decode()
    document = normalize_web_snapshot(_snapshot(body))
    pricing = _section_by_heading(document, "Pricing")
    assert pricing.locator.dom_path.endswith("/h2[2]") or "h2" in pricing.locator.dom_path
    assert pricing.locator.start_offset is not None
    assert pricing.locator.end_offset is not None
    snippet = raw[pricing.locator.start_offset : pricing.locator.end_offset]
    assert "Pricing" in snippet
    table = next(block for block in pricing.blocks if block.kind == "table")
    assert table.locator.dom_path.endswith("/table[1]") or "table" in table.locator.dom_path
    assert table.locator.start_offset is not None
    region = raw[table.locator.start_offset :]
    assert "Plan" in region


def test_normalized_document_is_versioned_replayable_and_immutable(tmp_path: Path) -> None:
    snapshot = _snapshot(_page(sections=V1_SECTIONS))
    first = normalize_web_snapshot(snapshot)
    second = normalize_web_snapshot(snapshot)
    assert first == second
    assert first.document_id == second.document_id
    assert first.normalizer_version == NORMALIZER_VERSION

    store = NormalizedDocumentStore(tmp_path / "normalized")
    stored = store.put(first)
    assert store.put(second).document_id == stored.document_id
    assert store.get_for_snapshot(snapshot.snapshot_id) == first
    assert store.list_ids() == (first.document_id,)

    mutated = replace(first, title="mutated-title")
    try:
        store.put(mutated)
    except NormalizedDocumentImmutabilityError:
        pass
    else:
        raise AssertionError("normalized store must refuse mutation")
    assert store.get(first.document_id) == first


def test_normalization_does_not_write_observations(tmp_path: Path) -> None:
    database = Database(tmp_path / "normalize.db")
    database.initialize()
    normalize_web_snapshot(_snapshot(_page(sections=V1_SECTIONS)))
    with database.connect() as connection:
        observations = connection.execute("SELECT COUNT(*) AS count FROM observations").fetchone()
        claims = connection.execute("SELECT COUNT(*) AS count FROM state_claims").fetchone()
    assert observations["count"] == 0
    assert claims["count"] == 0
