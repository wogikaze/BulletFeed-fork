from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel

BootstrapSubjectKind = Literal["event", "topic", "global"]
BootstrapEvidenceKind = Literal[
    "bootstrap_explicit",
    "bootstrap_checkpoint",
    "bootstrap_claim",
    "bootstrap_inferred",
]


class BootstrapClaimRequest(ApiModel):
    claim_ids: list[str] = Field(min_length=1, max_length=50)
    session_id: str | None = Field(default=None, max_length=80)


class BootstrapCheckpointRequest(ApiModel):
    subject_kind: BootstrapSubjectKind
    subject_id: str = Field(min_length=1, max_length=160)
    as_of: str | None = Field(default=None, max_length=40)
    catch_up: bool = False


class BootstrapEvidenceItem(ApiModel):
    id: str
    kind: BootstrapEvidenceKind
    provenance: str
    confidence: str
    source_id: str
    claim_id: str | None = None
    event_id: str | None = None
    created_at: int


class BootstrapCheckpointItem(ApiModel):
    subject_kind: str
    subject_id: str
    as_of: int
    catch_up: bool
    claim_ids: list[str]


class BootstrapSummaryResponse(ApiModel):
    version: str
    explicit_claim_ids: list[str]
    inferred_claim_ids: list[str]
    checkpoints: list[BootstrapCheckpointItem]
    evidence: list[BootstrapEvidenceItem]


class BootstrapClaimsResponse(ApiModel):
    version: str
    session_id: str
    claim_ids: list[str]


class BootstrapCheckpointResponse(ApiModel):
    version: str
    subject_kind: str
    subject_id: str
    as_of: int
    catch_up: bool
    claim_ids: list[str]
