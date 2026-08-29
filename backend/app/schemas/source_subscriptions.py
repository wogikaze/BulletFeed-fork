from typing import Literal

from pydantic import Field, model_validator

from app.schemas.common import ApiModel

UserSourceKind = Literal["statuspage", "rss_atom", "json_feed"]
SourceSubscriptionState = Literal["pending", "ok", "failing"]


class SourceSubscriptionCreate(ApiModel):
    kind: UserSourceKind
    url: str | None = Field(default=None, max_length=2_048)
    page_id: str | None = Field(default=None, max_length=64)
    catch_up: bool = False

    @model_validator(mode="after")
    def require_source_identity(self) -> "SourceSubscriptionCreate":
        has_url = bool(self.url and self.url.strip())
        has_page_id = bool(self.page_id and self.page_id.strip())
        if self.kind == "statuspage":
            if not has_url and not has_page_id:
                raise ValueError("pageId or url is required for statuspage")
            return self
        if not has_url:
            raise ValueError("url is required")
        return self


class SourceSubscriptionPublisher(ApiModel):
    slug: str
    display_name: str


class SourceSubscriptionStatus(ApiModel):
    selected: bool
    state: SourceSubscriptionState
    last_success_at: str | None = None
    last_attempt_at: str | None = None
    failure_count: int = 0
    next_run_at: str | None = None


class SourceSubscription(ApiModel):
    id: str
    kind: UserSourceKind
    canonical_url: str
    page_id: str | None = None
    publisher: SourceSubscriptionPublisher | None = None
    status: SourceSubscriptionStatus


class SourceSubscriptionList(ApiModel):
    items: list[SourceSubscription]
