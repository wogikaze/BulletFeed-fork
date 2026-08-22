from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

ImportanceLevel = Literal["critical", "high", "medium", "low"]
RelationLevel = Literal["direct", "adjacent", "reference"]
Confidence = Literal["high", "medium", "low"]
DeltaType = Literal["new_fact", "detail", "state_update", "correction", "unresolved_contradiction"]
FeedItemStatus = Literal["unread", "read"]
FeedbackType = Literal["important", "not_relevant"]
EventPhase = Literal["investigating", "identified", "monitoring", "resolved"]
TimelineType = Literal["announced", "state_changed", "information_added", "corrected", "resolved"]
SourceKind = Literal[
    "statuspage",
    "github_advisory",
    "osv",
    "github_release",
    "official_changelog",
    "documentation",
]
TopicType = Literal["technology", "service", "company"]
TopicPriority = Literal["high", "normal", "low"]
ImpactKind = Literal["explicit", "inferred"]


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ApiErrorBody(ApiModel):
    code: str
    message: str
    field: str | None = None


class ApiError(ApiModel):
    error: ApiErrorBody


class MatchedRepository(ApiModel):
    id: str
    name: str
    url: str


class Importance(ApiModel):
    level: ImportanceLevel
    reason: str
    confidence: Confidence


class Relation(ApiModel):
    level: RelationLevel
    reason: str
    matched_topics: list[str]
    matched_repositories: list[MatchedRepository]


class Delta(ApiModel):
    id: str
    type: DeltaType
    summary: str
    before: str
    after: str
    occurred_at: str


class CurrentState(ApiModel):
    phase: EventPhase
    summary: str
    since: str
    confidence: Confidence


class TimelineEntry(ApiModel):
    id: str
    type: TimelineType
    occurred_at: str
    title: str
    description: str
    delta_id: str | None = None
    state: dict[str, str] | None = None


class Impact(ApiModel):
    kind: ImpactKind
    text: str
    confidence: Confidence


class SourceEvidence(ApiModel):
    publisher: str
    kind: SourceKind
    title: str
    url: str
    published_at: str
    retrieved_at: str
    evidence: str


class SessionResponse(ApiModel):
    access_token: str
    user_id: str


def error_payload(code: str, message: str, field: str | None = None) -> dict[str, Any]:
    return ApiError(error=ApiErrorBody(code=code, message=message, field=field)).model_dump(by_alias=True)
