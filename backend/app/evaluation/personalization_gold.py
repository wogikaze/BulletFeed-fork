from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DATASET_VERSION = "personalization-v0.1"
LABEL_PROTOCOL_VERSION = "personalization-label-v1"
SOURCE_FAMILIES = (
    "github_release",
    "github_advisory",
    "osv",
    "statuspage",
    "rss_atom",
    "json_feed",
)
SplitName = Literal["pilot", "blind"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileRecord(_StrictModel):
    occupation: str
    interests: list[str]
    region: str


class TopicRecord(_StrictModel):
    name: str
    type: str
    priority: str = "normal"


class RepositoryRecord(_StrictModel):
    full_name: str
    language: str = ""


class PriorFeedbackRecord(_StrictModel):
    summary: str
    feedback: Literal["important", "not_relevant"]


class UserRecord(_StrictModel):
    user_id: str = Field(min_length=1)
    split: SplitName
    kind: Literal["cold_start", "history_rich"]
    profile: ProfileRecord
    topics: list[TopicRecord]
    repositories: list[RepositoryRecord]
    prior_feedback: list[PriorFeedbackRecord] = Field(default_factory=list)
    products: list[str] = Field(min_length=0)
    adjacent_products: list[str] = Field(default_factory=list)
    watches_security: bool = False


class ItemRecord(_StrictModel):
    item_id: str = Field(min_length=1)
    split: SplitName
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_family: Literal[
        "github_release",
        "github_advisory",
        "osv",
        "statuspage",
        "rss_atom",
        "json_feed",
    ]
    publisher: str
    url: str
    product: str
    kind: Literal["release", "advisory", "outage", "news"]
    redundancy_group: str = Field(min_length=1)
    tokens: list[str]
    lexical_traps_for: list[str] = Field(default_factory=list)
    adjacent_products: list[str] = Field(default_factory=list)
    ambiguous_for: list[str] = Field(default_factory=list)


class JudgmentRecord(_StrictModel):
    judgment_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    relevance: int = Field(ge=0, le=3)
    importance_to_user: int = Field(ge=0, le=3)
    should_surface: bool
    redundancy_group: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    ambiguous: bool = False
    hard_negative: bool = False
    label_protocol_version: str
    dataset_version: str
    split: SplitName


@dataclass(frozen=True)
class PersonalizationUser:
    user_id: str
    split: SplitName
    kind: str
    profile: ProfileRecord
    topics: tuple[TopicRecord, ...]
    repositories: tuple[RepositoryRecord, ...]
    prior_feedback: tuple[PriorFeedbackRecord, ...]
    products: tuple[str, ...]
    adjacent_products: tuple[str, ...]
    watches_security: bool


@dataclass(frozen=True)
class PersonalizationItem:
    item_id: str
    split: SplitName
    title: str
    summary: str
    source_family: str
    publisher: str
    url: str
    product: str
    kind: str
    redundancy_group: str
    tokens: tuple[str, ...]
    lexical_traps_for: tuple[str, ...]
    adjacent_products: tuple[str, ...]
    ambiguous_for: tuple[str, ...]


@dataclass(frozen=True)
class PersonalizationJudgment:
    judgment_id: str
    user_id: str
    item_id: str
    relevance: int
    importance_to_user: int
    should_surface: bool
    redundancy_group: str
    rationale: str
    provenance: str
    ambiguous: bool
    hard_negative: bool
    label_protocol_version: str
    dataset_version: str
    split: SplitName


@dataclass(frozen=True)
class PersonalizationGoldCorpus:
    dataset_version: str
    label_protocol_version: str
    users: tuple[PersonalizationUser, ...]
    items: tuple[PersonalizationItem, ...]
    judgments: tuple[PersonalizationJudgment, ...]

    def for_split(self, split: str) -> PersonalizationGoldCorpus:
        users = tuple(user for user in self.users if user.split == split)
        items = tuple(item for item in self.items if item.split == split)
        judgments = tuple(judgment for judgment in self.judgments if judgment.split == split)
        return PersonalizationGoldCorpus(
            dataset_version=self.dataset_version,
            label_protocol_version=self.label_protocol_version,
            users=users,
            items=items,
            judgments=judgments,
        )

    def user_by_id(self) -> dict[str, PersonalizationUser]:
        return {user.user_id: user for user in self.users}

    def item_by_id(self) -> dict[str, PersonalizationItem]:
        return {item.item_id: item for item in self.items}

    def judgments_for_user(self, user_id: str) -> tuple[PersonalizationJudgment, ...]:
        return tuple(judgment for judgment in self.judgments if judgment.user_id == user_id)

    def source_families(self) -> frozenset[str]:
        return frozenset(item.source_family for item in self.items)


@dataclass(frozen=True)
class PersonalizationMetrics:
    k: int
    precision_at_k: float
    recall_at_k: float
    ndcg_at_k: float
    redundancy_at_k: float
    user_count: int
    judgment_count: int
    irrelevant_item_rate: float = 0.0
    slice_name: str = "all"


@dataclass(frozen=True)
class PersonalizationEvaluationReport:
    dataset_version: str
    split: str | None
    k: int
    include_ambiguous: PersonalizationMetrics
    exclude_ambiguous: PersonalizationMetrics
    unresolved_ambiguous_count: int
    slices: dict[str, PersonalizationMetrics] = field(default_factory=dict)


def load_personalization_gold(corpus_dir: Path) -> PersonalizationGoldCorpus:
    users = tuple(
        _user_from_record(UserRecord.model_validate(raw))
        for raw in _load_json_array(corpus_dir / "users.json")
    )
    items = tuple(
        _item_from_record(ItemRecord.model_validate(raw))
        for raw in _load_json_array(corpus_dir / "items.json")
    )
    judgments = tuple(
        _judgment_from_record(JudgmentRecord.model_validate(raw))
        for raw in _load_json_array(corpus_dir / "judgments.json")
    )
    corpus = PersonalizationGoldCorpus(
        dataset_version=DATASET_VERSION,
        label_protocol_version=LABEL_PROTOCOL_VERSION,
        users=users,
        items=items,
        judgments=judgments,
    )
    validate_personalization_corpus(corpus)
    return corpus


def load_label_schema(schema_path: Path) -> dict[str, Any]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise ValueError("label schema must be an object")
    return schema


def validate_judgment_against_schema(judgment: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    definition = schema.get("$defs", {}).get("judgment")
    if not isinstance(definition, dict):
        raise ValueError("label schema is missing $defs.judgment")
    _validate_json_schema(judgment, definition, path="judgment")


def validate_personalization_corpus(corpus: PersonalizationGoldCorpus) -> None:
    if not corpus.users:
        raise ValueError("corpus has no users")
    if not corpus.items:
        raise ValueError("corpus has no items")
    if not corpus.judgments:
        raise ValueError("corpus has no judgments")

    user_ids = [user.user_id for user in corpus.users]
    item_ids = [item.item_id for item in corpus.items]
    judgment_ids = [judgment.judgment_id for judgment in corpus.judgments]
    _assert_unique("user_id", user_ids)
    _assert_unique("item_id", item_ids)
    _assert_unique("judgment_id", judgment_ids)

    users = corpus.user_by_id()
    items = corpus.item_by_id()
    for judgment in corpus.judgments:
        if judgment.user_id not in users:
            raise ValueError(f"judgment {judgment.judgment_id} references unknown user")
        if judgment.item_id not in items:
            raise ValueError(f"judgment {judgment.judgment_id} references unknown item")
        if judgment.dataset_version != DATASET_VERSION:
            raise ValueError(f"judgment {judgment.judgment_id} has unexpected dataset_version")
        if judgment.label_protocol_version != LABEL_PROTOCOL_VERSION:
            raise ValueError(f"judgment {judgment.judgment_id} has unexpected label_protocol_version")
        user = users[judgment.user_id]
        item = items[judgment.item_id]
        if judgment.split != user.split or judgment.split != item.split:
            raise ValueError(f"judgment {judgment.judgment_id} crosses split boundaries")
        if judgment.redundancy_group != item.redundancy_group:
            raise ValueError(f"judgment {judgment.judgment_id} redundancy_group does not match item")

    assert_split_partition(corpus)


def assert_split_partition(corpus: PersonalizationGoldCorpus) -> None:
    groups: dict[str, dict[str, set[str]]] = {
        "pilot": {"user": set(), "item": set(), "judgment": set()},
        "blind": {"user": set(), "item": set(), "judgment": set()},
    }
    for user in corpus.users:
        groups[user.split]["user"].add(user.user_id)
    for item in corpus.items:
        groups[item.split]["item"].add(item.item_id)
    for judgment in corpus.judgments:
        groups[judgment.split]["judgment"].add(judgment.judgment_id)

    for kind in ("user", "item", "judgment"):
        overlap = groups["pilot"][kind] & groups["blind"][kind]
        if overlap:
            raise ValueError(f"pilot/{kind} IDs overlap the held-out split: {sorted(overlap)[:8]}")


def scan_python_sources(root: Path, forbidden: Iterable[str]) -> tuple[str, ...]:
    tokens = tuple(token for token in forbidden if token)
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        hits = sorted(token for token in tokens if token in text)
        if hits:
            violations.append(f"{path}: {', '.join(hits)}")
    return tuple(violations)


def evaluate_personalization(
    corpus: PersonalizationGoldCorpus,
    predicted: Mapping[str, Sequence[str]],
    *,
    k: int = 10,
    split: str | None = None,
) -> PersonalizationEvaluationReport:
    if k < 1:
        raise ValueError("k must be >= 1")
    scoped = corpus.for_split(split) if split is not None else corpus
    include = _metrics_for_judgments(scoped, predicted, k=k, drop_ambiguous=False)
    exclude = _metrics_for_judgments(scoped, predicted, k=k, drop_ambiguous=True)
    unresolved = sum(1 for judgment in scoped.judgments if judgment.ambiguous)
    kinds = sorted({user.kind for user in scoped.users})
    slices = {
        kind: _metrics_for_judgments(
            scoped,
            predicted,
            k=k,
            drop_ambiguous=False,
            kinds={kind},
            slice_name=kind,
        )
        for kind in kinds
    }
    return PersonalizationEvaluationReport(
        dataset_version=scoped.dataset_version,
        split=split,
        k=k,
        include_ambiguous=include,
        exclude_ambiguous=exclude,
        unresolved_ambiguous_count=unresolved,
        slices=slices,
    )


def _metrics_for_judgments(
    corpus: PersonalizationGoldCorpus,
    predicted: Mapping[str, Sequence[str]],
    *,
    k: int,
    drop_ambiguous: bool,
    kinds: set[str] | None = None,
    slice_name: str = "all",
) -> PersonalizationMetrics:
    items = corpus.item_by_id()
    precisions: list[float] = []
    recalls: list[float] = []
    ndcgs: list[float] = []
    redundancies: list[float] = []
    irrelevant_rates: list[float] = []
    used_judgments = 0

    for user in corpus.users:
        if kinds is not None and user.kind not in kinds:
            continue
        selected = [
            judgment
            for judgment in corpus.judgments_for_user(user.user_id)
            if not (drop_ambiguous and judgment.ambiguous)
        ]
        if not selected:
            continue
        used_judgments += len(selected)
        by_item = {judgment.item_id: judgment for judgment in selected}
        ranking = [item_id for item_id in predicted.get(user.user_id, ()) if item_id in by_item]
        labeled = [judgment.item_id for judgment in selected]
        for item_id in labeled:
            if item_id not in ranking:
                ranking.append(item_id)
        top = ranking[:k]

        surfaced = {judgment.item_id for judgment in selected if judgment.should_surface}
        hits = sum(1 for item_id in top if item_id in surfaced)
        precisions.append(hits / k)
        recalls.append(hits / len(surfaced) if surfaced else 1.0)
        gains = [by_item[item_id].relevance if item_id in by_item else 0 for item_id in top]
        ideal = sorted((judgment.relevance for judgment in selected), reverse=True)[:k]
        ndcgs.append(_ndcg(gains, ideal))
        irrelevant = sum(
            1
            for item_id in top
            if item_id in by_item and by_item[item_id].relevance == 0
        )
        irrelevant_rates.append(irrelevant / k)

        seen_groups: set[str] = set()
        redundant = 0
        for item_id in top:
            if item_id in by_item:
                group = by_item[item_id].redundancy_group
            elif item_id in items:
                group = items[item_id].redundancy_group
            else:
                group = item_id
            if group in seen_groups:
                redundant += 1
            seen_groups.add(group)
        redundancies.append(redundant / k)

    if not precisions:
        empty = PersonalizationMetrics(k, 0.0, 0.0, 0.0, 0.0, 0, 0, 0.0, slice_name)
        return empty
    return PersonalizationMetrics(
        k=k,
        precision_at_k=sum(precisions) / len(precisions),
        recall_at_k=sum(recalls) / len(recalls),
        ndcg_at_k=sum(ndcgs) / len(ndcgs),
        redundancy_at_k=sum(redundancies) / len(redundancies),
        user_count=len(precisions),
        judgment_count=used_judgments,
        irrelevant_item_rate=sum(irrelevant_rates) / len(irrelevant_rates),
        slice_name=slice_name,
    )


def _ndcg(gains: Sequence[int], ideal: Sequence[int]) -> float:
    dcg = _dcg(gains)
    idcg = _dcg(ideal)
    if idcg == 0:
        return 1.0
    return dcg / idcg


def _dcg(gains: Sequence[int]) -> float:
    total = 0.0
    for index, relevance in enumerate(gains, start=1):
        total += (math.pow(2, relevance) - 1.0) / math.log2(index + 1)
    return total


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path.name} must be a JSON array")
    return payload


def _user_from_record(record: UserRecord) -> PersonalizationUser:
    return PersonalizationUser(
        user_id=record.user_id,
        split=record.split,
        kind=record.kind,
        profile=record.profile,
        topics=tuple(record.topics),
        repositories=tuple(record.repositories),
        prior_feedback=tuple(record.prior_feedback),
        products=tuple(record.products),
        adjacent_products=tuple(record.adjacent_products),
        watches_security=record.watches_security,
    )


def _item_from_record(record: ItemRecord) -> PersonalizationItem:
    return PersonalizationItem(
        item_id=record.item_id,
        split=record.split,
        title=record.title,
        summary=record.summary,
        source_family=record.source_family,
        publisher=record.publisher,
        url=record.url,
        product=record.product,
        kind=record.kind,
        redundancy_group=record.redundancy_group,
        tokens=tuple(record.tokens),
        lexical_traps_for=tuple(record.lexical_traps_for),
        adjacent_products=tuple(record.adjacent_products),
        ambiguous_for=tuple(record.ambiguous_for),
    )


def _judgment_from_record(record: JudgmentRecord) -> PersonalizationJudgment:
    return PersonalizationJudgment(
        judgment_id=record.judgment_id,
        user_id=record.user_id,
        item_id=record.item_id,
        relevance=record.relevance,
        importance_to_user=record.importance_to_user,
        should_surface=record.should_surface,
        redundancy_group=record.redundancy_group,
        rationale=record.rationale,
        provenance=record.provenance,
        ambiguous=record.ambiguous,
        hard_negative=record.hard_negative,
        label_protocol_version=record.label_protocol_version,
        dataset_version=record.dataset_version,
        split=record.split,
    )


def _assert_unique(label: str, values: Sequence[str]) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label} values")


def _validate_json_schema(instance: Any, schema: Mapping[str, Any], *, path: str) -> None:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(instance, dict):
            raise ValueError(f"{path} must be an object")
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                raise ValueError(f"{path} missing required property {key}")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                _validate_json_schema(value, properties[key], path=f"{path}.{key}")
        return
    if expected_type == "string":
        if not isinstance(instance, str):
            raise ValueError(f"{path} must be a string")
        if "minLength" in schema and len(instance) < int(schema["minLength"]):
            raise ValueError(f"{path} is shorter than minLength")
        if "enum" in schema and instance not in schema["enum"]:
            raise ValueError(f"{path} is not an allowed enum value")
        return
    if expected_type == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            raise ValueError(f"{path} must be an integer")
        if "minimum" in schema and instance < int(schema["minimum"]):
            raise ValueError(f"{path} is below minimum")
        if "maximum" in schema and instance > int(schema["maximum"]):
            raise ValueError(f"{path} is above maximum")
        return
    if expected_type == "boolean":
        if not isinstance(instance, bool):
            raise ValueError(f"{path} must be a boolean")
        return
    if expected_type == "array":
        if not isinstance(instance, list):
            raise ValueError(f"{path} must be an array")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, value in enumerate(instance):
                _validate_json_schema(value, item_schema, path=f"{path}[{index}]")
        return
