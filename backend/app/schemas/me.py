from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel, Confidence, TopicPriority, TopicType

OnboardingState = Literal["profile", "github_pending", "repository_pending", "ready"]


class Profile(ApiModel):
    occupation: str
    interests: list[str]
    region: str


class ProfileUpdate(ApiModel):
    occupation: str = Field(min_length=1, max_length=80)
    interests: list[str] = Field(min_length=1)
    region: str = ""


class MeBootstrap(ApiModel):
    onboarding_completed: bool
    onboarding_state: OnboardingState
    profile: Profile
    topic_count: int
    github_connected: bool


class Topic(ApiModel):
    id: str
    name: str
    type: TopicType
    priority: TopicPriority
    order: int
    created_at: str


class TopicCreate(ApiModel):
    name: str = Field(min_length=1, max_length=80)
    type: TopicType = "technology"


class TopicPatch(ApiModel):
    priority: TopicPriority | None = None
    order: int | None = Field(default=None, ge=0)


class TopicList(ApiModel):
    items: list[Topic]


class TopicSearchResult(ApiModel):
    items: list[Topic]


TopicRecommendationProvenance = Literal["explicit", "inferred"]


class TopicRecommendationItem(ApiModel):
    id: str
    name: str
    type: TopicType
    score: float
    reason: str
    provenance: TopicRecommendationProvenance
    already_followed: bool
    confidence: Confidence
    source_signals: list[str]


class TopicRecommendationList(ApiModel):
    version: str
    items: list[TopicRecommendationItem]
    policy_version: str
    cohort: str


class OnboardingRequest(ApiModel):
    profile: ProfileUpdate
    topics: list[str] = Field(default_factory=list, max_length=20)
    connect_github: bool = False


class GithubAuthorizationHint(ApiModel):
    required: bool
    authorization_url: str | None = None


class OnboardingResponse(ApiModel):
    completed: bool
    state: OnboardingState
    github_authorization: GithubAuthorizationHint
