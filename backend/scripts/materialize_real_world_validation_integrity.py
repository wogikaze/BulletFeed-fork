"""Materialize #117 corpus integrity files: split isolation + fetch artifacts.

Run from the repository root. Re-fetching live HTTPS is optional; existing
artifacts are reused unless --refetch is passed. Does not touch production
ranking or knownness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "backend" / "tests" / "gold" / "real_world_validation" / "v01"
USER_AGENT = "BulletFeed-local-prototype/0.1 (+local evaluation corpus)"
REQUESTED_AT = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

PERSONA_INDEPENDENCE_NOTE = (
    "Constructed profiles are clustered by persona_template. Do not treat "
    "len(profiles) as independent n for bootstrap CIs; cluster by persona family."
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _save_artifact(source_id: str, body: bytes, meta: dict[str, Any]) -> Path:
    directory = CORPUS / "artifacts" / source_id
    directory.mkdir(parents=True, exist_ok=True)
    body_path = directory / "body.bin"
    body_path.write_bytes(body)
    _write_json(directory / "meta.json", meta)
    return body_path


def _fetch(url: str, *, accept: str | None = None) -> tuple[bytes, dict[str, Any]]:
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-HTTPS fetch: {url}")
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers, method="GET")
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            body = response.read()
            info = response.info()
            meta = {
                "url": url,
                "requested_at": REQUESTED_AT,
                "http_status": int(response.status),
                "content_type": info.get("Content-Type"),
                "final_url": str(response.geturl()),
                "etag": info.get("ETag"),
                "last_modified": info.get("Last-Modified"),
            }
            return body, meta
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GET {url} failed: HTTP {exc.code}") from exc


def _json_loads(body: bytes) -> dict[str, Any]:
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    return payload


def _html_time(html: str) -> str | None:
    match = re.search(r"<time[^>]*datetime=['\"]([^'\"]+)['\"]", html, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _html_title(html: str) -> str | None:
    match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _load_existing_profiles() -> list[dict[str, Any]]:
    root_profiles = CORPUS / "profiles.json"
    if root_profiles.is_file():
        profiles = json.loads(root_profiles.read_text(encoding="utf-8"))
        if len(profiles) != 50:
            raise SystemExit(f"expected 50 constructed profiles, found {len(profiles)}")
        return profiles
    profiles: list[dict[str, Any]] = []
    for split in ("pilot", "dev", "blind"):
        path = CORPUS / split / "profiles.json"
        if path.is_file():
            profiles.extend(json.loads(path.read_text(encoding="utf-8")))
    if len(profiles) != 50:
        raise SystemExit(f"expected 50 constructed profiles, found {len(profiles)}")
    return profiles


def _index(split: str, sources: list[dict[str, Any]], events: list[dict[str, Any]], profiles: list[dict[str, Any]], judgments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "split": split,
        "source_ids": [row["source_id"] for row in sources],
        "event_ids": [row["event_id"] for row in events],
        "profile_ids": [row["profile_id"] for row in profiles],
        "judgment_ids": [row["judgment_id"] for row in judgments],
    }


def _source(
    *,
    source_id: str,
    canonical_url: str,
    publisher: str,
    source_family: str,
    information_type: str,
    language: str,
    event_id: str | None,
    split: str,
    source_role: str,
    fetch_kind: str,
    fetch_meta: dict[str, Any],
    content_hash: str,
    evidence_locator: str,
    evidence_text: str,
    normalized_evidence: str,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "canonical_url": canonical_url,
        "publisher": publisher,
        "source_family": source_family,
        "information_type": information_type,
        "language": language,
        "collected_at": fetch_meta["requested_at"],
        "content_hash": content_hash,
        "evidence_locator": evidence_locator,
        "event_id": event_id,
        "split": split,
        "source_role": source_role,
        "fetch": {
            "fetch_kind": fetch_kind,
            "url": fetch_meta["url"],
            "requested_at": fetch_meta["requested_at"],
            "http_status": fetch_meta["http_status"],
            "content_type": fetch_meta.get("content_type"),
            "final_url": fetch_meta["final_url"],
            "etag": fetch_meta.get("etag"),
            "last_modified": fetch_meta.get("last_modified"),
            "artifact_relpath": f"artifacts/{source_id}/body.bin",
        },
        "evidence_text": evidence_text,
        "normalized_evidence": normalized_evidence,
        "static_fetch_ok": True,
        "static_normalize_insufficient": False,
        "js_render_would_recover": False,
    }


def _event(
    *,
    event_id: str,
    split: str,
    title: str,
    information_type: str,
    language: str,
    record_kind: str,
    is_real_event: bool,
    published_at: str | None,
    updated_at: str | None,
    observed_at: str | None,
    occurred_at: str | None,
    occurred_at_provenance: str | None,
    occurred_at_basis: str | None,
    provenance: str,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "split": split,
        "title": title,
        "information_type": information_type,
        "language": language,
        "redundancy_group": f"rg_{event_id}",
        "mirror_group": f"mg_{event_id}",
        "record_kind": record_kind,
        "is_real_event": is_real_event,
        "published_at": published_at,
        "updated_at": updated_at,
        "observed_at": observed_at,
        "effective_at": None,
        "occurred_at": occurred_at,
        "occurred_at_provenance": occurred_at_provenance,
        "occurred_at_basis": occurred_at_basis,
        "provenance": provenance,
    }


def _materialize_contract_fixture(source_id: str, evidence: str) -> tuple[bytes, dict[str, Any], str]:
    body = evidence.encode("utf-8")
    meta = {
        "url": f"local-contract-fixture:{source_id}",
        "requested_at": "2026-08-29T00:00:00Z",
        "http_status": 200,
        "content_type": "text/plain; charset=utf-8",
        "final_url": f"local-contract-fixture:{source_id}",
        "etag": None,
        "last_modified": None,
        "fetch_kind": "local_contract_fixture",
        "note": "Synthetic contract fixture bytes. Not a live page fetch.",
    }
    _save_artifact(source_id, body, meta)
    return body, meta, _sha256(body)


def _reuse_or_fetch(source_id: str, url: str, *, accept: str | None, refetch: bool) -> tuple[bytes, dict[str, Any]]:
    body_path = CORPUS / "artifacts" / source_id / "body.bin"
    meta_path = CORPUS / "artifacts" / source_id / "meta.json"
    if body_path.is_file() and meta_path.is_file() and not refetch:
        return body_path.read_bytes(), json.loads(meta_path.read_text(encoding="utf-8"))
    body, meta = _fetch(url, accept=accept)
    if meta["http_status"] != 200:
        raise RuntimeError(f"{url} returned HTTP {meta['http_status']}")
    _save_artifact(source_id, body, meta)
    return body, meta


def _github_release(source_id: str, owner: str, repo: str, tag: str, refetch: bool) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    api = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    body, meta = _reuse_or_fetch(source_id, api, accept="application/vnd.github+json", refetch=refetch)
    payload = _json_loads(body)
    return payload, body, meta


def _github_tag_commit(source_id: str, owner: str, repo: str, tag: str, refetch: bool) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    """Go (and similar) tags are often not GitHub Release objects. Resolve the tag to its commit."""
    ref_url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/tags/{tag}"
    ref_body, _ref_meta = _fetch(ref_url, accept="application/vnd.github+json")
    ref = _json_loads(ref_body)
    sha = ref["object"]["sha"]
    if ref["object"]["type"] == "tag":
        commit_url = f"https://api.github.com/repos/{owner}/{repo}/git/tags/{sha}"
    else:
        commit_url = f"https://api.github.com/repos/{owner}/{repo}/git/commits/{sha}"
    body, meta = _reuse_or_fetch(source_id, commit_url, accept="application/vnd.github+json", refetch=refetch)
    meta = {
        **meta,
        "resolved_from_ref": ref_url,
        "tag": tag,
    }
    _save_artifact(source_id, body, meta)
    return _json_loads(body), body, meta


def _github_advisory(source_id: str, ghsa: str, refetch: bool) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    api = f"https://api.github.com/advisories/{ghsa}"
    body, meta = _reuse_or_fetch(source_id, api, accept="application/vnd.github+json", refetch=refetch)
    return _json_loads(body), body, meta


def _osv(source_id: str, cve: str, refetch: bool) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    api = f"https://api.osv.dev/v1/vulns/{cve}"
    body, meta = _reuse_or_fetch(source_id, api, accept="application/json", refetch=refetch)
    return _json_loads(body), body, meta


def _html_page(source_id: str, url: str, refetch: bool) -> tuple[str, bytes, dict[str, Any]]:
    body, meta = _reuse_or_fetch(source_id, url, accept="text/html,application/xhtml+xml", refetch=refetch)
    return body.decode("utf-8", errors="replace"), body, meta


def materialize(*, refetch: bool) -> None:
    profiles = _load_existing_profiles()
    by_split_profiles = {"pilot": [], "dev": [], "blind": []}
    for row in profiles:
        by_split_profiles[row["split"]].append(row)

    contract_specs = (
        (
            "pilot",
            "src_contract_p01",
            "evt_contract_p01",
            "https://github.com/bulletfeed-contract/pilot-example/releases/tag/v0.0.1",
            "GitHub",
            "github_release",
            "release",
            "pilot-contract-evidence",
            "Pilot contract release v0.0.1",
            "contract-fixture-pilot",
        ),
        (
            "dev",
            "src_contract_d01",
            "evt_contract_d01",
            "https://status.example-contract-dev.com/incidents/dev-001",
            "Example Status",
            "statuspage",
            "incident",
            "dev-contract-evidence",
            "Dev contract incident",
            "contract-fixture-dev",
        ),
        (
            "blind",
            "src_contract_h01",
            "evt_contract_h01",
            "https://osv.dev/vulnerability/OSV-CONTRACT-HOLD-01",
            "OSV",
            "osv",
            "security",
            "blind-contract-evidence",
            "Holdout contract advisory",
            "contract-fixture-holdout",
        ),
    )

    sources: dict[str, list[dict[str, Any]]] = {"pilot": [], "dev": [], "blind": []}
    events: dict[str, list[dict[str, Any]]] = {"pilot": [], "dev": [], "blind": []}

    for split, source_id, event_id, url, publisher, family, info_type, evidence, title, provenance in contract_specs:
        _, meta, digest = _materialize_contract_fixture(source_id, evidence)
        sources[split].append(
            _source(
                source_id=source_id,
                canonical_url=url,
                publisher=publisher,
                source_family=family,
                information_type=info_type,
                language="en",
                event_id=event_id,
                split=split,
                source_role="contract_fixture",
                fetch_kind="local_contract_fixture",
                fetch_meta={
                    "url": url,
                    "requested_at": "2026-08-29T00:00:00Z",
                    "http_status": 200,
                    "content_type": meta["content_type"],
                    "final_url": url,
                    "etag": None,
                    "last_modified": None,
                },
                content_hash=digest,
                evidence_locator=f"{url}#body",
                evidence_text=evidence,
                normalized_evidence=title,
            )
        )
        events[split].append(
            _event(
                event_id=event_id,
                split=split,
                title=title,
                information_type=info_type,
                language="en",
                record_kind="contract_fixture",
                is_real_event=False,
                published_at=None,
                updated_at=None,
                observed_at=None,
                occurred_at=None,
                occurred_at_provenance=None,
                occurred_at_basis=None,
                provenance=provenance,
            )
        )

    rust, rust_body, rust_meta = _github_release("src_rw_p_rust180", "rust-lang", "rust", "1.80.0", refetch)
    rust_evidence = rust["tag_name"]
    if rust_evidence not in rust_body.decode("utf-8"):
        raise RuntimeError("Rust tag_name missing from artifact")
    sources["pilot"].append(
        _source(
            source_id="src_rw_p_rust180",
            canonical_url="https://github.com/rust-lang/rust/releases/tag/1.80.0",
            publisher="GitHub",
            source_family="github_release",
            information_type="release",
            language="en",
            event_id="evt_rw_p_rust180",
            split="pilot",
            source_role="event_page",
            fetch_kind="live_https",
            fetch_meta={**rust_meta, "url": "https://api.github.com/repos/rust-lang/rust/releases/tags/1.80.0"},
            content_hash=_sha256(rust_body),
            evidence_locator="json_pointer:/tag_name",
            evidence_text=rust_evidence,
            normalized_evidence="Rust 1.80.0",
        )
    )
    events["pilot"].append(
        _event(
            event_id="evt_rw_p_rust180",
            split="pilot",
            title="Rust 1.80.0",
            information_type="release",
            language="en",
            record_kind="event_update",
            is_real_event=True,
            published_at=rust.get("published_at"),
            updated_at=None,
            observed_at=rust_meta["requested_at"],
            occurred_at=rust.get("published_at"),
            occurred_at_provenance="github_release.published_at",
            occurred_at_basis=str(rust.get("published_at")),
            provenance="github-api:https://api.github.com/repos/rust-lang/rust/releases/tags/1.80.0",
        )
    )

    ghsa, ghsa_body, ghsa_meta = _github_advisory("src_rw_p_ghsa", "GHSA-7rjr-3q55-vv33", refetch)
    ghsa_evidence = ghsa["ghsa_id"]
    sources["pilot"].append(
        _source(
            source_id="src_rw_p_ghsa",
            canonical_url="https://github.com/advisories/GHSA-7rjr-3q55-vv33",
            publisher="GitHub",
            source_family="github_advisory",
            information_type="security",
            language="en",
            event_id="evt_rw_p_ghsa",
            split="pilot",
            source_role="event_page",
            fetch_kind="live_https",
            fetch_meta={**ghsa_meta, "url": "https://api.github.com/advisories/GHSA-7rjr-3q55-vv33"},
            content_hash=_sha256(ghsa_body),
            evidence_locator="json_pointer:/ghsa_id",
            evidence_text=ghsa_evidence,
            normalized_evidence="GHSA-7rjr-3q55-vv33",
        )
    )
    events["pilot"].append(
        _event(
            event_id="evt_rw_p_ghsa",
            split="pilot",
            title="GHSA-7rjr-3q55-vv33",
            information_type="security",
            language="en",
            record_kind="event_update",
            is_real_event=True,
            published_at=ghsa.get("published_at"),
            updated_at=ghsa.get("updated_at"),
            observed_at=ghsa_meta["requested_at"],
            occurred_at=ghsa.get("published_at"),
            occurred_at_provenance="github_advisory.published_at",
            occurred_at_basis=str(ghsa.get("published_at")),
            provenance="github-api:https://api.github.com/advisories/GHSA-7rjr-3q55-vv33",
        )
    )

    osv, osv_body, osv_meta = _osv("src_rw_p_osv", "CVE-2023-4863", refetch)
    osv_evidence = osv["id"]
    sources["pilot"].append(
        _source(
            source_id="src_rw_p_osv",
            canonical_url="https://osv.dev/vulnerability/CVE-2023-4863",
            publisher="OSV",
            source_family="osv",
            information_type="security",
            language="en",
            event_id="evt_rw_p_osv",
            split="pilot",
            source_role="event_page",
            fetch_kind="live_https",
            fetch_meta={**osv_meta, "url": "https://api.osv.dev/v1/vulns/CVE-2023-4863"},
            content_hash=_sha256(osv_body),
            evidence_locator="json_pointer:/id",
            evidence_text=osv_evidence,
            normalized_evidence="OSV CVE-2023-4863",
        )
    )
    events["pilot"].append(
        _event(
            event_id="evt_rw_p_osv",
            split="pilot",
            title="OSV CVE-2023-4863",
            information_type="security",
            language="en",
            record_kind="event_update",
            is_real_event=True,
            published_at=osv.get("published"),
            updated_at=osv.get("modified"),
            observed_at=osv_meta["requested_at"],
            occurred_at=osv.get("published"),
            occurred_at_provenance="osv.published",
            occurred_at_basis=str(osv.get("published")),
            provenance="osv-api:https://api.osv.dev/v1/vulns/CVE-2023-4863",
        )
    )

    go, go_body, go_meta = _github_tag_commit("src_rw_d_go123", "golang", "go", "go1.23.0", refetch)
    go_evidence = "go1.23.0"
    go_text = go_body.decode("utf-8")
    if go_evidence not in go_text and go.get("sha"):
        go_evidence = go["sha"]
    if go_evidence not in go_text:
        raise RuntimeError("Go 1.23.0 commit artifact is missing a stable locator")
    go_published = (go.get("committer") or {}).get("date") or (go.get("tagger") or {}).get("date")
    go_locator = "json_pointer:/committer/date" if (go.get("committer") or {}).get("date") else "json_pointer:/sha"
    sources["dev"].append(
        _source(
            source_id="src_rw_d_go123",
            canonical_url="https://github.com/golang/go/releases/tag/go1.23.0",
            publisher="GitHub",
            source_family="github_release",
            information_type="release",
            language="en",
            event_id="evt_rw_d_go123",
            split="dev",
            source_role="event_page",
            fetch_kind="live_https",
            fetch_meta={**go_meta, "url": go_meta.get("final_url") or go_meta["url"]},
            content_hash=_sha256(go_body),
            evidence_locator=go_locator,
            evidence_text=go_evidence,
            normalized_evidence="Go 1.23.0",
        )
    )
    events["dev"].append(
        _event(
            event_id="evt_rw_d_go123",
            split="dev",
            title="Go 1.23.0",
            information_type="release",
            language="en",
            record_kind="event_update",
            is_real_event=True,
            published_at=go_published,
            updated_at=None,
            observed_at=go_meta["requested_at"],
            occurred_at=go_published,
            occurred_at_provenance="github_git_commit.committer.date",
            occurred_at_basis=str(go_published),
            provenance="github-api:git-commit-for-tag:go1.23.0",
        )
    )

    ghsa2, ghsa2_body, ghsa2_meta = _github_advisory("src_rw_d_advisory", "GHSA-p6mc-m468-83gw", refetch)
    sources["dev"].append(
        _source(
            source_id="src_rw_d_advisory",
            canonical_url="https://github.com/advisories/GHSA-p6mc-m468-83gw",
            publisher="GitHub",
            source_family="github_advisory",
            information_type="security",
            language="en",
            event_id="evt_rw_d_advisory",
            split="dev",
            source_role="event_page",
            fetch_kind="live_https",
            fetch_meta={**ghsa2_meta, "url": "https://api.github.com/advisories/GHSA-p6mc-m468-83gw"},
            content_hash=_sha256(ghsa2_body),
            evidence_locator="json_pointer:/ghsa_id",
            evidence_text=ghsa2["ghsa_id"],
            normalized_evidence="GHSA-p6mc-m468-83gw",
        )
    )
    events["dev"].append(
        _event(
            event_id="evt_rw_d_advisory",
            split="dev",
            title="GHSA-p6mc-m468-83gw",
            information_type="security",
            language="en",
            record_kind="event_update",
            is_real_event=True,
            published_at=ghsa2.get("published_at"),
            updated_at=ghsa2.get("updated_at"),
            observed_at=ghsa2_meta["requested_at"],
            occurred_at=ghsa2.get("published_at"),
            occurred_at_provenance="github_advisory.published_at",
            occurred_at_basis=str(ghsa2.get("published_at")),
            provenance="github-api:https://api.github.com/advisories/GHSA-p6mc-m468-83gw",
        )
    )

    rust_html, rust_html_body, rust_html_meta = _html_page(
        "src_rw_d_rustblog",
        "https://blog.rust-lang.org/2024/06/13/Rust-1.79.0/",
        refetch,
    )
    rust_time = _html_time(rust_html)
    rust_title = _html_title(rust_html) or "Announcing Rust 1.79.0"
    rust_blog_evidence = "Announcing Rust 1.79.0"
    if rust_blog_evidence not in rust_html:
        rust_blog_evidence = rust_title
        if rust_blog_evidence not in rust_html:
            raise RuntimeError("Rust 1.79 blog title not found in fetched HTML")
    rust_visible = "June 13, 2024"
    rust_occurred = rust_time
    rust_prov = "html_time_datetime" if rust_time else None
    rust_basis = rust_time
    if rust_occurred is None and rust_visible in rust_html:
        rust_occurred = "2024-06-13T00:00:00Z"
        rust_prov = "html_visible_publish_date"
        rust_basis = rust_visible
    if rust_occurred is None:
        rust_prov = None
        rust_basis = None
    sources["dev"].append(
        _source(
            source_id="src_rw_d_rustblog",
            canonical_url="https://blog.rust-lang.org/2024/06/13/Rust-1.79.0/",
            publisher="Rust Blog",
            source_family="official_changelog",
            information_type="release",
            language="en",
            event_id="evt_rw_d_rustblog",
            split="dev",
            source_role="event_page",
            fetch_kind="live_https",
            fetch_meta={**rust_html_meta, "url": "https://blog.rust-lang.org/2024/06/13/Rust-1.79.0/"},
            content_hash=_sha256(rust_html_body),
            evidence_locator="css:title",
            evidence_text=rust_blog_evidence,
            normalized_evidence="Rust 1.79.0 announcement",
        )
    )
    events["dev"].append(
        _event(
            event_id="evt_rw_d_rustblog",
            split="dev",
            title="Rust 1.79.0 announcement",
            information_type="release",
            language="en",
            record_kind="event_update",
            is_real_event=True,
            published_at=rust_occurred,
            updated_at=None,
            observed_at=rust_html_meta["requested_at"],
            occurred_at=rust_occurred,
            occurred_at_provenance=rust_prov,
            occurred_at_basis=rust_basis,
            provenance="html-fetch:https://blog.rust-lang.org/2024/06/13/Rust-1.79.0/",
        )
    )

    react_html, react_body, react_meta = _html_page(
        "src_rw_d_react",
        "https://react.dev/blog/2024/12/05/react-19",
        refetch,
    )
    react_time = _html_time(react_html)
    react_title = _html_title(react_html) or "React 19"
    react_evidence = "React v19"
    if react_evidence not in react_html:
        react_evidence = "React 19"
        if react_evidence not in react_html:
            raise RuntimeError("React 19 string not found in fetched HTML")
    react_visible = "December 05, 2024"
    react_occurred = react_time
    react_prov = "html_time_datetime" if react_time else None
    react_basis = react_time
    if react_occurred is None and react_visible in react_html:
        react_occurred = "2024-12-05T00:00:00Z"
        react_prov = "html_visible_publish_date"
        react_basis = react_visible
    if react_occurred is None:
        react_prov = None
        react_basis = None
    sources["dev"].append(
        _source(
            source_id="src_rw_d_react",
            canonical_url="https://react.dev/blog/2024/12/05/react-19",
            publisher="React",
            source_family="official_changelog",
            information_type="roadmap_changelog",
            language="en",
            event_id="evt_rw_d_react",
            split="dev",
            source_role="event_page",
            fetch_kind="live_https",
            fetch_meta={**react_meta, "url": "https://react.dev/blog/2024/12/05/react-19"},
            content_hash=_sha256(react_body),
            evidence_locator="css:title" if react_title else "html_substring:React 19",
            evidence_text=react_evidence,
            normalized_evidence="React 19",
        )
    )
    events["dev"].append(
        _event(
            event_id="evt_rw_d_react",
            split="dev",
            title="React 19",
            information_type="roadmap_changelog",
            language="en",
            record_kind="event_update",
            is_real_event=True,
            published_at=react_occurred,
            updated_at=None,
            observed_at=react_meta["requested_at"],
            occurred_at=react_occurred,
            occurred_at_provenance=react_prov,
            occurred_at_basis=react_basis,
            provenance="html-fetch:https://react.dev/blog/2024/12/05/react-19",
        )
    )

    cpy, cpy_body, cpy_meta = _github_tag_commit("src_rw_h_cpython", "python", "cpython", "v3.12.4", refetch)
    cpy_text = cpy_body.decode("utf-8")
    cpy_evidence = "Python 3.12.4" if "Python 3.12.4" in cpy_text else cpy.get("sha", "")
    if not cpy_evidence or cpy_evidence not in cpy_text:
        raise RuntimeError("CPython 3.12.4 commit artifact is missing a stable locator")
    cpy_published = (cpy.get("committer") or {}).get("date") or (cpy.get("tagger") or {}).get("date")
    sources["blind"].append(
        _source(
            source_id="src_rw_h_cpython",
            canonical_url="https://github.com/python/cpython/releases/tag/v3.12.4",
            publisher="GitHub",
            source_family="github_release",
            information_type="release",
            language="en",
            event_id="evt_rw_h_cpython",
            split="blind",
            source_role="event_page",
            fetch_kind="live_https",
            fetch_meta={**cpy_meta, "url": cpy_meta.get("final_url") or cpy_meta["url"]},
            content_hash=_sha256(cpy_body),
            evidence_locator="json_pointer:/message",
            evidence_text=cpy_evidence,
            normalized_evidence="CPython 3.12.4",
        )
    )
    events["blind"].append(
        _event(
            event_id="evt_rw_h_cpython",
            split="blind",
            title="CPython 3.12.4",
            information_type="release",
            language="en",
            record_kind="event_update",
            is_real_event=True,
            published_at=cpy_published,
            updated_at=None,
            observed_at=cpy_meta["requested_at"],
            occurred_at=cpy_published,
            occurred_at_provenance="github_git_commit.committer.date",
            occurred_at_basis=str(cpy_published),
            provenance="github-api:git-commit-for-tag:v3.12.4",
        )
    )

    osv2, osv2_body, osv2_meta = _osv("src_rw_h_osv2", "CVE-2024-3094", refetch)
    sources["blind"].append(
        _source(
            source_id="src_rw_h_osv2",
            canonical_url="https://osv.dev/vulnerability/CVE-2024-3094",
            publisher="OSV",
            source_family="osv",
            information_type="security",
            language="en",
            event_id="evt_rw_h_osv2",
            split="blind",
            source_role="event_page",
            fetch_kind="live_https",
            fetch_meta={**osv2_meta, "url": "https://api.osv.dev/v1/vulns/CVE-2024-3094"},
            content_hash=_sha256(osv2_body),
            evidence_locator="json_pointer:/id",
            evidence_text=osv2["id"],
            normalized_evidence="OSV CVE-2024-3094",
        )
    )
    events["blind"].append(
        _event(
            event_id="evt_rw_h_osv2",
            split="blind",
            title="OSV CVE-2024-3094",
            information_type="security",
            language="en",
            record_kind="event_update",
            is_real_event=True,
            published_at=osv2.get("published"),
            updated_at=osv2.get("modified"),
            observed_at=osv2_meta["requested_at"],
            occurred_at=osv2.get("published"),
            occurred_at_provenance="osv.published",
            occurred_at_basis=str(osv2.get("published")),
            provenance="osv-api:https://api.osv.dev/v1/vulns/CVE-2024-3094",
        )
    )

    ghsa3, ghsa3_body, ghsa3_meta = _github_advisory("src_rw_h_npm", "GHSA-jfh8-c2jp-5v3q", refetch)
    sources["blind"].append(
        _source(
            source_id="src_rw_h_npm",
            canonical_url="https://github.com/advisories/GHSA-jfh8-c2jp-5v3q",
            publisher="GitHub",
            source_family="github_advisory",
            information_type="security",
            language="en",
            event_id="evt_rw_h_npm",
            split="blind",
            source_role="event_page",
            fetch_kind="live_https",
            fetch_meta={**ghsa3_meta, "url": "https://api.github.com/advisories/GHSA-jfh8-c2jp-5v3q"},
            content_hash=_sha256(ghsa3_body),
            evidence_locator="json_pointer:/ghsa_id",
            evidence_text=ghsa3["ghsa_id"],
            normalized_evidence="GHSA-jfh8-c2jp-5v3q",
        )
    )
    events["blind"].append(
        _event(
            event_id="evt_rw_h_npm",
            split="blind",
            title="GHSA-jfh8-c2jp-5v3q",
            information_type="security",
            language="en",
            record_kind="event_update",
            is_real_event=True,
            published_at=ghsa3.get("published_at"),
            updated_at=ghsa3.get("updated_at"),
            observed_at=ghsa3_meta["requested_at"],
            occurred_at=ghsa3.get("published_at"),
            occurred_at_provenance="github_advisory.published_at",
            occurred_at_basis=str(ghsa3.get("published_at")),
            provenance="github-api:https://api.github.com/advisories/GHSA-jfh8-c2jp-5v3q",
        )
    )

    judgments = {
        "pilot": [
            {
                "judgment_id": "jdg_contract_p01",
                "profile_id": "prf_contract_p01",
                "event_id": "evt_contract_p01",
                "split": "pilot",
                "stratum": "clear_positive",
                "relevance": 3,
                "importance_to_user": 2,
                "known_before": False,
                "should_surface": True,
                "rationale": "Followed repository released a version the constructed profile would want.",
                "provenance": "contract-fixture-pilot",
                "label_protocol_version": "label-protocol-v1",
                "dataset_version": "real-world-validation-v0.2",
                "ambiguous": False,
            }
        ],
        "dev": [
            {
                "judgment_id": "jdg_contract_d01",
                "profile_id": "prf_contract_d01",
                "event_id": "evt_contract_d01",
                "split": "dev",
                "stratum": "already_known",
                "relevance": 2,
                "importance_to_user": 1,
                "known_before": True,
                "should_surface": False,
                "rationale": "History-rich profile already marked this incident known.",
                "provenance": "contract-fixture-dev",
                "label_protocol_version": "label-protocol-v1",
                "dataset_version": "real-world-validation-v0.2",
                "ambiguous": False,
            }
        ],
        "blind": [
            {
                "judgment_id": "jdg_contract_h01",
                "profile_id": "prf_contract_h01",
                "event_id": "evt_contract_h01",
                "split": "blind",
                "stratum": "hard_negative",
                "relevance": 0,
                "importance_to_user": 0,
                "known_before": False,
                "should_surface": False,
                "rationale": "Holdout stratum example. Do not embed this id in production modules.",
                "provenance": "contract-fixture-holdout",
                "label_protocol_version": "label-protocol-v1",
                "dataset_version": "real-world-validation-v0.2",
                "ambiguous": False,
            }
        ],
    }

    manifest = {
        "dataset_id": "bulletfeed-real-world-validation-v0.2",
        "dataset_version": "real-world-validation-v0.2",
        "contract_version": "real-world-validation-contract-v1.2",
        "label_protocol_version": "label-protocol-v1",
        "required_source_fields": [
            "source_id",
            "canonical_url",
            "publisher",
            "source_family",
            "information_type",
            "language",
            "collected_at",
            "content_hash",
            "evidence_locator",
            "event_id",
            "split",
            "source_role",
            "fetch",
            "evidence_text",
            "normalized_evidence",
        ],
        "targets": {
            "min_events": 500,
            "min_profiles": 96,
            "min_judgments": 10000,
            "min_source_families": 6,
            "min_authoritative_endpoints": 120,
            "min_persona_families": 24,
        },
        "splits": ["pilot", "dev", "blind"],
        "leakage_checks": [
            "canonical_url",
            "event_id",
            "mirror_group",
            "profile_id",
            "redundancy_group",
        ],
        "files": {
            "judgment_schema": "judgments/schema.json",
            "artifacts": "artifacts/{source_id}/body.bin",
            "artifact_meta": "artifacts/{source_id}/meta.json",
            "split_sources": "{split}/sources.json",
            "split_events": "{split}/events.json",
            "split_profiles": "{split}/profiles.json",
            "split_judgments": "{split}/judgments.json",
            "split_index": "{split}/index.json",
        },
        "production_behavior_changed": False,
        "phase": "corpus-expansion",
        "note": (
            "Bootstrap-only materializer for the v1.2 corpus contract. Blind labels "
            "are physical files and content_hash binds to saved fetch artifacts. "
            "Use collect_real_world_validation_batch.py and the versioned label "
            "generator for the expanded corpus."
        ),
        "persona_independence_note": PERSONA_INDEPENDENCE_NOTE,
    }
    _write_json(CORPUS / "manifest.json", manifest)

    schema_path = CORPUS / "judgments" / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["$defs"]["judgment"]["properties"]["dataset_version"] = {
        "const": "real-world-validation-v0.2"
    }
    _write_json(schema_path, schema)

    for split in ("pilot", "dev", "blind"):
        _write_json(CORPUS / split / "sources.json", sources[split])
        _write_json(CORPUS / split / "events.json", events[split])
        _write_json(CORPUS / split / "profiles.json", by_split_profiles[split])
        _write_json(CORPUS / split / "judgments.json", judgments[split])
        _write_json(
            CORPUS / split / "index.json",
            _index(split, sources[split], events[split], by_split_profiles[split], judgments[split]),
        )

    for stale in ("sources.json", "events.json", "profiles.json"):
        path = CORPUS / stale
        if path.exists():
            path.unlink()
    records = CORPUS / "judgments" / "records.json"
    if records.exists():
        records.unlink()

    real = sum(1 for split in events.values() for row in split if row["is_real_event"])
    print(f"materialized integrity corpus: real_events={real} profiles={len(profiles)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refetch", action="store_true")
    args = parser.parse_args()
    materialize(refetch=args.refetch)


if __name__ == "__main__":
    main()
