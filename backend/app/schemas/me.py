from pydantic import Field

from app.schemas.common import ApiModel, TopicPriority, TopicType


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


class OnboardingRequest(ApiModel):
    profile: ProfileUpdate
    topics: list[str] = Field(min_length=5)
    connect_github: bool = False


class GithubAuthorizationHint(ApiModel):
    required: bool
    authorization_url: str | None = None


class OnboardingResponse(ApiModel):
    completed: bool
    github_authorization: GithubAuthorizationHint
