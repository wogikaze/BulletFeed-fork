import pytest

from scripts.select_m6_top3_clusters import _select_persona_families


def test_m6_selection_uses_measured_failure_count_and_minimum() -> None:
    report = {
        "metrics": {
            "failure_taxonomy": {
                "by_dimension": {
                    "important_unknown_missed": {
                        "persona_family": {
                            "small": 19,
                            "largest": 30,
                            "middle": 21,
                        }
                    }
                }
            }
        }
    }

    assert _select_persona_families(report, 2) == ("largest", "middle")


def test_m6_selection_rejects_insufficient_clusters() -> None:
    report = {
        "metrics": {
            "failure_taxonomy": {
                "by_dimension": {
                    "important_unknown_missed": {
                        "persona_family": {"only": 20}
                    }
                }
            }
        }
    }

    with pytest.raises(ValueError, match="only 1"):
        _select_persona_families(report, 3)
