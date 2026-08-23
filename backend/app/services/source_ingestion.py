from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.database import Database
from app.stores.observation_store import Observation, ObservationStore


@dataclass(frozen=True)
class NormalizedObservation:
    source_type: str
    source_key: str
    source_observation_id: str
    payload: dict[str, Any]
    original_url: str
    published_at: str | None


class SourceIngestionPipeline:
    """Source-agnostic append-only observation ingestion.

    Source adapters are responsible for fetching and normalization. This layer only
    persists normalized observations with the same idempotency guarantees for every
    source family.
    """

    def __init__(self, database: Database) -> None:
        self._observations = ObservationStore(database)

    def ingest_many(
        self,
        items: Iterable[NormalizedObservation],
        *,
        retrieved_at: str,
    ) -> tuple[Observation, ...]:
        return tuple(
            self._observations.append(
                source_type=item.source_type,
                source_key=item.source_key,
                source_observation_id=item.source_observation_id,
                payload=item.payload,
                original_url=item.original_url,
                published_at=item.published_at,
                retrieved_at=retrieved_at,
            )
            for item in items
        )
