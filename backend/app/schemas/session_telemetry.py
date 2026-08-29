from typing import Literal

from app.schemas.common import ApiModel

SessionOutcomeKind = Literal[
    "session_start",
    "card_displayed",
    "detail_read",
    "feedback",
    "follow",
    "session_end",
]


class FeedSessionResponse(ApiModel):
    version: str
    id: str
    started_at: int
    ended_at: int | None = None


class SessionMetricsResponse(ApiModel):
    version: str
    session_count: int
    displayed_count: int
    useful_card_rate: float | None = None
    already_known_reshow_rate: float | None = None
    cards_to_useful_item: float | None = None
    feedback_response_rate: float | None = None
