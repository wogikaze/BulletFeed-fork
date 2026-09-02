from app.evaluation.m1_zero_to_useful import M1Persona
from scripts.run_m1_api_qualification import STAGES, _summary, _topic_selection


def test_api_trace_keeps_acquisition_projection_and_evidence_ordered() -> None:
    assert [
        STAGES.index(stage)
        for stage in ("acquisition", "projection", "feed", "evidence")
    ] == sorted(
        STAGES.index(stage)
        for stage in ("acquisition", "projection", "feed", "evidence")
    )


def test_topic_selection_keeps_persona_interest_and_deduplicates_fillers() -> None:
    persona = M1Persona(
        persona_id="test",
        cohort="cold_start",
        language="ja",
        breadth="narrow",
        security="low",
        topics=("React",),
    )

    assert _topic_selection(persona) == ["React", "TypeScript", "Python", "Rust", "Kubernetes"]


def test_api_qualification_summary_preserves_empty_persona_samples() -> None:
    summary = _summary(
        [
            {
                "surfaced": 2,
                "useful_proxy_at_5": 2,
                "useful_proxy_at_10": 2,
                "cards_to_first_useful": 1,
            },
            {
                "surfaced": 0,
                "useful_proxy_at_5": 0,
                "useful_proxy_at_10": 0,
                "cards_to_first_useful": None,
            },
        ]
    )

    assert summary["sample_count"] == 2
    assert summary["surfaced_card_count"] == 2
    assert summary["useful_proxy_at_5_total"] == 2
    assert summary["useful_proxy_at_10_total"] == 2
    assert summary["cards_to_first_useful"] == {
        "sample_count": 1,
        "median": 1,
        "max": 1,
    }
