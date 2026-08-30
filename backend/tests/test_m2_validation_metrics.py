from types import SimpleNamespace

import pytest

from app.evaluation.m2_validation_metrics import (
    build_personalization_corpus,
    evaluate_m2_production_scoring,
)


def _corpus(*, include_blind: bool = False) -> SimpleNamespace:
    manifest = SimpleNamespace(
        dataset_version="real-world-validation-v0.2",
        label_protocol_version="label-protocol-v1",
    )
    event = SimpleNamespace(
        event_id="evt_real",
        split="pilot",
        title="React 19 release",
        information_type="release",
        language="en",
        redundancy_group="rg_react",
        is_real_event=True,
    )
    source = SimpleNamespace(
        event_id="evt_real",
        source_id="src_react",
        source_role="event_page",
        source_family="package_registry",
        publisher="npm registry / react",
        canonical_url="https://registry.npmjs.org/react/19.0.0",
        normalized_evidence="React 19 release",
        fetch=SimpleNamespace(content_type="application/json"),
    )
    profile = SimpleNamespace(
        profile_id="prf_react",
        split="pilot",
        cohort="cold_start",
        persona_template="frontend_engineer",
        language_focus="en",
        explicit_interests=["React"],
        selected_repositories=[],
        prior_feedback=[],
        followed_products=[],
        security_sensitivity="low",
    )
    judgment = SimpleNamespace(
        judgment_id="jdg_react",
        profile_id="prf_react",
        event_id="evt_real",
        split="pilot",
        relevance=3,
        importance_to_user=2,
        known_before=False,
        should_surface=True,
        rationale="direct interest",
        provenance="AI-silver; test",
        ambiguous=False,
        stratum="clear_positive",
        label_protocol_version="label-protocol-v1",
        dataset_version="real-world-validation-v0.2",
    )
    if include_blind:
        blind_event = SimpleNamespace(**{**vars(event), "event_id": "evt_blind", "split": "blind"})
        blind_profile = SimpleNamespace(
            **{**vars(profile), "profile_id": "prf_blind", "split": "blind"}
        )
        blind_judgment = SimpleNamespace(
            **{
                **vars(judgment),
                "judgment_id": "jdg_blind",
                "profile_id": "prf_blind",
                "event_id": "evt_blind",
                "split": "blind",
            }
        )
        return SimpleNamespace(
            manifest=manifest,
            events=[event, blind_event],
            sources=[source],
            profiles=[profile, blind_profile],
            judgments=[judgment, blind_judgment],
        )
    return SimpleNamespace(
        manifest=manifest,
        events=[event],
        sources=[source],
        profiles=[profile],
        judgments=[judgment],
    )


def test_m2_production_metrics_use_shared_ranker_without_blind_records() -> None:
    corpus = _corpus()

    adapted, metadata = build_personalization_corpus(corpus)
    report = evaluate_m2_production_scoring(corpus, bootstrap_replicates=3)

    assert len(adapted.users) == 1
    assert len(adapted.items) == 1
    assert metadata["evt_real"].source_family == "package_registry"
    assert report["blind_records_loaded"] is False
    assert report["sample"] == {
        "profile_count": 1,
        "real_event_count": 1,
        "judgment_count": 1,
        "persona_family_count": 1,
    }
    assert report["headline"]["include_ambiguous"]["at_5"]["precision_at_5"] == 0.2
    assert report["headline"]["include_ambiguous"]["at_10"]["precision_at_10"] == 0.1
    assert report["uncertainty"]["headline"]["at_10"]["status"] == "not_available"
    assert report["failure_taxonomy"]["covered_stage"] == "ranking"
    assert report["stage_attribution"]["status"] == "partial"


def test_m2_production_metrics_reject_blind_input() -> None:
    with pytest.raises(ValueError, match="blind"):
        build_personalization_corpus(_corpus(include_blind=True))
