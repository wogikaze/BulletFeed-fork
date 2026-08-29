from __future__ import annotations

import unicodedata
from pathlib import Path

from app.evaluation.delta_adversarial_gold import (
    load_delta_adversarial_gold,
)
from app.services.claim_semantics import canonicalize_text, compare_claims
from app.services.multilingual_normalize import (
    detect_language,
    extract_identifiers,
    metrics_by_language,
    normalize_multilingual,
    pair_language,
    prepare_for_english_canonicalize,
)
from app.services.semantic_delta import ClaimSnapshot, DeltaContext, judge_revision

_V01 = Path(__file__).parent / "gold" / "delta_adversarial" / "v01"


def test_japanese_segmentation_does_not_rely_on_whitespace() -> None:
    compact = normalize_multilingual("Python3.10は未対応です")
    spaced = normalize_multilingual("Python 3.10 は 未対応 です")

    assert compact.language == "mixed"
    assert "3.10" in compact.tokens
    assert "not" in compact.tokens
    assert "supported" in compact.tokens
    assert compact.tokens == spaced.tokens
    assert all(" " not in token for token in compact.tokens)


def test_fullwidth_punctuation_dates_and_numbers_normalize() -> None:
    fullwidth = normalize_multilingual("Ｐｙｔｈｏｎ　３．１０は２０２５年１０月３１日に終了")
    halfwidth = normalize_multilingual("Python 3.10は2025年10月31日に終了")

    assert "3.10" in fullwidth.tokens
    assert "2025-10-31" in fullwidth.tokens
    assert "end" in fullwidth.tokens
    assert fullwidth.tokens == halfwidth.tokens

    numbered = normalize_multilingual("上限は１，０００件です。")
    assert "1000" in "".join(canonicalize_text(numbered.text).numbers + canonicalize_text(numbered.text).tokens)


def test_embedded_english_technical_ids_remain_intact() -> None:
    text = "GHSA-f283-ghqc-fg79 の CookieJar は CVE-2024-12345 と requests 2.31.0 の影響を受けます。"
    normalized = normalize_multilingual(text)
    identifiers = extract_identifiers(text)
    canonical = canonicalize_text(text)

    assert "GHSA-f283-ghqc-fg79" in identifiers
    assert "CVE-2024-12345" in identifiers
    assert "2.31.0" in identifiers
    assert "GHSA-f283-ghqc-fg79" in normalized.tokens
    assert "CVE-2024-12345" in normalized.tokens
    assert "2.31.0" in normalized.tokens
    assert "cookiejar" in canonical.tokens
    assert "ghsa-f283-ghqc-fg79" in canonical.tokens
    assert "cve-2024-12345" in canonical.tokens
    assert "2.31.0" in canonical.versions


def test_negation_and_comparators_are_not_normalized_away() -> None:
    supported = canonicalize_text("Python 3.10は対応しています")
    missing = canonicalize_text("Python 3.10は未対応です")
    unsupported = canonicalize_text("Python 3.10は非対応です")
    nai = canonicalize_text("回避策はない")
    present = canonicalize_text("回避策はある")
    ge = canonicalize_text("Python 3.10以上")
    le = canonicalize_text("Python 3.10以下")

    assert supported.negated is False
    assert missing.negated is True
    assert unsupported.negated is True
    assert nai.negated is True
    assert present.negated is False
    assert compare_claims(supported.text, "", missing.text, "").label == "not_equivalent"
    assert compare_claims(supported.text, "", unsupported.text, "").label == "not_equivalent"
    assert compare_claims(nai.text, "", present.text, "").label == "not_equivalent"
    assert ">=" in ge.tokens
    assert "<=" in le.tokens
    assert ge.tokens != le.tokens
    assert compare_claims(ge.text, "", le.text, "").label == "not_equivalent"


def test_language_detection_and_unknown_fallback_are_conservative() -> None:
    assert detect_language("Actions workflows are failing to start.") == "en"
    assert detect_language("サポートは終了します。") == "ja"
    assert detect_language("Actions のワークフロー起動に失敗しています。") == "mixed"
    assert detect_language("") == "unknown"
    assert detect_language("!!!") == "unknown"
    assert detect_language("3.10") == "unknown"
    assert pair_language("サポートは終了します。", "Python 3.9 support ends.") == "mixed"
    assert pair_language("3.10", "!!!") == "unknown"

    fallback = normalize_multilingual("3.10")
    assert fallback.language == "unknown"
    assert fallback.fallback is True
    assert "3.10" in fallback.identifiers
    assert prepare_for_english_canonicalize("3.10").strip() == "3.10"


def test_english_prepare_is_nfkc_stable_for_gold_prose() -> None:
    samples = (
        "Limit increased to 1,000 requests per minute.",
        "Limit was raised to one thousand requests/min.",
        "Retires July 30, 2026",
        "Retires 2026/07/30",
        "Python 3.10 is not supported",
        "Widget v3 is available with migration notes",
        "fixed in v2.1.0",
        "Japan rollout is available for enterprise users",
    )
    for sample in samples:
        assert prepare_for_english_canonicalize(sample) == unicodedata.normalize("NFKC", sample)
        assert detect_language(sample) == "en"


def test_delta_adversarial_metrics_are_reported_by_language() -> None:
    corpus = load_delta_adversarial_gold(_V01)
    rows: list[tuple[str, str, bool, bool]] = []
    coref = {"ja": [0, 0], "en": [0, 0], "mixed": [0, 0], "unknown": [0, 0]}
    languages = {"ja": 0, "en": 0, "mixed": 0}
    for case in corpus.cases:
        prior_text = f"{case.prior.value} {case.prior.detail}"
        candidate_text = f"{case.candidate.value} {case.candidate.detail}"
        language = pair_language(prior_text, candidate_text)
        if language in languages:
            languages[language] += 1
        equivalence = compare_claims(
            case.prior.value,
            case.prior.detail,
            case.candidate.value,
            case.candidate.detail,
        )
        rows.append(
            (
                prior_text,
                candidate_text,
                case.equivalence == "equivalent",
                equivalence.label == "equivalent",
            )
        )
        decision = judge_revision(
            ClaimSnapshot(
                value=case.prior.value,
                detail=case.prior.detail,
                valid_at=case.prior.valid_at,
            ),
            ClaimSnapshot(
                value=case.candidate.value,
                detail=case.candidate.detail,
                valid_at=case.candidate.valid_at,
            ),
            context=DeltaContext(
                explicit_correction=case.explicit_correction,
                unresolved_source_conflict=case.unresolved_source_conflict,
            ),
        )
        predicted_same = decision.revision_type != "NEW_FACT"
        if not case.same_gold_event and predicted_same:
            coref[language][0] += 1
        elif case.same_gold_event and not predicted_same:
            coref[language][1] += 1

    report = metrics_by_language(rows)
    assert languages["ja"] >= 1
    assert languages["en"] >= 1
    assert languages["mixed"] >= 1
    assert report["ja"]["pair_count"] == languages["ja"]
    assert report["en"]["pair_count"] == languages["en"]
    assert report["mixed"]["pair_count"] == languages["mixed"]
    for language in ("ja", "en", "mixed"):
        assert 0.0 <= float(report[language]["precision"]) <= 1.0
        assert 0.0 <= float(report[language]["recall"]) <= 1.0
        assert coref[language][0] >= 0
        assert coref[language][1] >= 0

    japanese_family = [case for case in corpus.cases if case.family == "japanese_mixed_technical"]
    assert japanese_family
    assert {pair_language(f"{case.prior.value} {case.prior.detail}", f"{case.candidate.value} {case.candidate.detail}") for case in japanese_family} <= {
        "ja",
        "mixed",
    }
