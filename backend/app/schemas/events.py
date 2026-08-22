from app.schemas.common import ApiModel, CurrentState, Delta, Impact, SourceEvidence, TimelineEntry


class EventDetail(ApiModel):
    id: str
    title: str
    summary: str
    current_state: CurrentState
    latest_delta: Delta
    opened_delta: Delta | None = None
    timeline: list[TimelineEntry]
    impacts: list[Impact]
    sources: list[SourceEvidence]
    following: bool


class FollowingRequest(ApiModel):
    following: bool


class FollowingResponse(ApiModel):
    event_id: str
    following: bool
