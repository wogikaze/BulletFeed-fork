from scripts.build_m6_root_cause_report import _root_cause


def _row(relation_level: str, personalization_rank: int) -> dict[str, object]:
    return {
        "relation_level": relation_level,
        "personalization_rank": personalization_rank,
    }


def test_root_cause_identifies_dominant_semantic_identity_gap() -> None:
    rows = [_row("reference", 0) for _ in range(3)] + [_row("adjacent", 100)]

    assert _root_cause(rows).startswith("semantic_identity_gap:")


def test_root_cause_preserves_mixed_relation_signal() -> None:
    rows = [_row("reference", 0), _row("adjacent", 100)]

    assert _root_cause(rows).startswith("mixed_relation_gap:")


def test_root_cause_identifies_capacity_when_relation_is_available() -> None:
    rows = [_row("adjacent", 100) for _ in range(2)]

    assert _root_cause(rows).startswith("ranking_priority_or_capacity:")
