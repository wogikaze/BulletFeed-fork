from app.schemas.common import ApiModel, CurrentState, Delta, Impact, SourceEvidence, TimelineEntry


class EventSearchItem(ApiModel):
    id: str
    title: str
    summary: str
    current_phase: str
    current_summary: str
    updated_at: str
    following: bool
    source_publisher: str | None = None


class EventSearchPage(ApiModel):
    items: list[EventSearchItem]
    next_cursor: str | None = None


class UnknownFact(ApiModel):
    id: str
    text: str


class EventDetail(ApiModel):
    id: str
    title: str
    summary: str
    current_state: CurrentState
    latest_delta: Delta
    opened_delta: Delta | None = None
    unknown_facts: list[UnknownFact] = []
    timeline: list[TimelineEntry]
    impacts: list[Impact]
    sources: list[SourceEvidence]
    following: bool


class FollowingRequest(ApiModel):
    following: bool
    catch_up: bool = False


class FollowingResponse(ApiModel):
    event_id: str
    following: bool
