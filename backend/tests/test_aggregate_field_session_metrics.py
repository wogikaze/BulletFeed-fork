from scripts.aggregate_field_session_metrics import aggregate_metrics, normalize_metrics


def test_normalize_accepts_camel_case_api_payload() -> None:
    row = normalize_metrics(
        {
            "version": "session-telemetry-v1",
            "sessionCount": 2,
            "displayedCount": 4,
            "usefulCardRate": 0.5,
            "alreadyKnownReshowRate": 0.25,
            "cardsToUsefulItem": 2.0,
            "feedbackResponseRate": 0.75,
        }
    )
    assert row["session_count"] == 2
    assert row["displayed_count"] == 4
    assert row["useful_card_rate"] == 0.5
    assert row["already_known_reshow_rate"] == 0.25
    assert row["cards_to_useful_item"] == 2.0
    assert row["feedback_response_rate"] == 0.75


def test_aggregate_weights_rates_by_displayed_count_and_never_passes_gate() -> None:
    report = aggregate_metrics(
        [
            {
                "session_count": 1,
                "displayed_count": 2,
                "useful_card_rate": 1.0,
                "already_known_reshow_rate": 0.0,
                "cards_to_useful_item": 1.0,
                "feedback_response_rate": 1.0,
            },
            {
                "sessionCount": 3,
                "displayedCount": 6,
                "usefulCardRate": 0.0,
                "alreadyKnownReshowRate": 0.5,
                "cardsToUsefulItem": 3.0,
                "feedbackResponseRate": 0.5,
            },
        ]
    )
    assert report["completion_gate_pass"] is False
    assert report["blind_read"] is False
    assert report["participant_snapshot_count"] == 2
    assert report["session_count"] == 4
    assert report["displayed_count"] == 8
    assert report["useful_card_rate"] == 0.25
    assert report["already_known_reshow_rate"] == 0.375
    assert report["cards_to_useful_item"] == 2.0
    assert report["feedback_response_rate"] == 0.625


def test_aggregate_keeps_null_rates_when_nothing_was_displayed() -> None:
    report = aggregate_metrics(
        [{"session_count": 1, "displayed_count": 0, "useful_card_rate": None}]
    )
    assert report["useful_card_rate"] is None
    assert report["already_known_reshow_rate"] is None
    assert report["cards_to_useful_item"] is None
    assert report["feedback_response_rate"] is None
    assert report["completion_gate_pass"] is False
