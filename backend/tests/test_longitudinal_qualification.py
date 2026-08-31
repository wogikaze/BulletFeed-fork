from app.evaluation.longitudinal_qualification import (
    PROTOCOL_VERSION,
    Observation,
    classify_pair,
    summarize_outcomes,
)


def _obs(**overrides: object) -> Observation:
    payload = {
        "source_id": "src_demo",
        "source_family": "package_registry",
        "fetch_url": "https://pypi.org/pypi/requests/json",
        "acquired_at": "2026-08-31T00:00:00Z",
        "status_code": 200,
        "final_url": "https://pypi.org/pypi/requests/json",
        "content_type": "application/json",
        "content_hash": "abc",
        "etag": '"v1"',
        "last_modified": None,
        "error_type": None,
    }
    payload.update(overrides)
    return Observation(**payload)  # type: ignore[arg-type]


def test_hash_change_is_updated_not_synthesized() -> None:
    first = _obs()
    second = _obs(content_hash="def", acquired_at="2026-08-31T01:00:00Z")
    assert classify_pair(first, second) == "updated"


def test_same_hash_is_unchanged() -> None:
    assert classify_pair(_obs(), _obs(acquired_at="2026-08-31T01:00:00Z")) == "unchanged"


def test_conditional_304_is_not_an_update() -> None:
    second = _obs(status_code=304, content_hash=None)
    assert classify_pair(_obs(), second) == "conditional_304"


def test_missing_second_fetch_is_unavailable_not_updated() -> None:
    assert classify_pair(_obs(), None) == "unavailable"


def test_timeout_and_5xx_are_failures_not_updates() -> None:
    assert classify_pair(_obs(), _obs(status_code=None, error_type="timeout")) == "timeout"
    assert classify_pair(_obs(), _obs(status_code=503, content_hash=None)) == "http_error"


def test_final_url_change_is_identity_change() -> None:
    second = _obs(final_url="https://pypi.org/pypi/requests/json?moved=1")
    assert classify_pair(_obs(), second) == "identity_change"


def test_summary_records_zero_failure_as_remediation_not_required() -> None:
    rows = [
        (_obs(source_id="a"), _obs(source_id="a", acquired_at="2026-08-31T01:00:00Z")),
        (_obs(source_id="b", content_hash="x"), _obs(source_id="b", content_hash="x")),
    ]
    report = summarize_outcomes(rows)
    assert report["protocol_version"] == PROTOCOL_VERSION
    assert report["observed_failure_count"] == 0
    assert report["remediation"] == "remediation_not_required"
    assert report["missing_second_fetch_not_counted_as_update"] is True
    assert report["complete_pair_count"] == 2
    assert report["unavailable_count"] == 0


def test_timeout_summary_requires_remediation() -> None:
    second = _obs(status_code=None, error_type="timeout")
    report = summarize_outcomes([(_obs(), second)])
    assert report["remediation"] == "required"
    assert report["observed_failure_count"] == 1


def test_unavailable_pairs_are_incomplete_not_remediation_not_required() -> None:
    report = summarize_outcomes([(_obs(), None)])
    assert report["remediation"] == "collection_incomplete"
    assert report["unavailable_count"] == 1
    assert report["observed_failure_count"] == 0
