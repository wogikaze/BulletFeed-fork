from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.database import Database
from app.dependencies import get_database, require_user
from app.schemas.me import (
    MeBootstrap,
    OnboardingRequest,
    OnboardingResponse,
    Profile,
    ProfileUpdate,
    Topic,
    TopicCreate,
    TopicList,
    TopicPatch,
    TopicSearchResult,
)
from app.stores.me_store import MeStore

router = APIRouter(prefix="/v1", tags=["me"])


def _store(database: Annotated[Database, Depends(get_database)]) -> MeStore:
    return MeStore(database)


@router.get("/me", response_model=MeBootstrap)
def get_me(
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[MeStore, Depends(_store)],
) -> MeBootstrap:
    return store.bootstrap(user["user_id"])


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[MeStore, Depends(_store)],
) -> Response:
    store.delete_account(user["user_id"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/profile", response_model=Profile)
def get_profile(
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[MeStore, Depends(_store)],
) -> Profile:
    return store.get_profile(user["user_id"])


@router.put("/me/profile", response_model=Profile)
def update_profile(
    body: ProfileUpdate,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[MeStore, Depends(_store)],
) -> Profile:
    return store.save_profile(user["user_id"], body.occupation, body.interests, body.region)


@router.get("/me/topics", response_model=TopicList)
def list_topics(
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[MeStore, Depends(_store)],
) -> TopicList:
    return TopicList(items=store.list_topics(user["user_id"]))


@router.post("/me/topics", response_model=Topic, status_code=status.HTTP_201_CREATED)
def add_topic(
    body: TopicCreate,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[MeStore, Depends(_store)],
) -> Topic:
    return store.add_topic(user["user_id"], body.name, body.type)


@router.delete("/me/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_topic(
    topic_id: str,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[MeStore, Depends(_store)],
) -> Response:
    store.delete_topic(user["user_id"], topic_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/me/topics/{topic_id}", response_model=Topic)
def patch_topic(
    topic_id: str,
    body: TopicPatch,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[MeStore, Depends(_store)],
) -> Topic:
    return store.patch_topic(user["user_id"], topic_id, body.priority, body.order)


@router.get("/topics/search", response_model=TopicSearchResult)
def search_topics(
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[MeStore, Depends(_store)],
    q: Annotated[str, Query(min_length=1)],
) -> TopicSearchResult:
    return TopicSearchResult(items=store.search_topics(q))


@router.put("/me/onboarding", response_model=OnboardingResponse)
def complete_onboarding(
    body: OnboardingRequest,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[MeStore, Depends(_store)],
) -> OnboardingResponse:
    return OnboardingResponse.model_validate(
        store.complete_onboarding(
            user["user_id"],
            body.profile.occupation,
            body.profile.interests,
            body.profile.region,
            body.topics,
            body.connect_github,
        )
    )
