from __future__ import annotations

import hashlib
import html
import json
import os
import re
import secrets
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from app.services.source_catalog import SourceKind, source_allows_claim_evidence
from app.services.web_snapshots import WebSnapshot

NORMALIZER_VERSION = "web-normalize-v1"
ALIGNER_VERSION = "web-align-v1"
DOCUMENT_ID_PREFIX = "norm_"
SECTION_ID_PREFIX = "sec_"
BLOCK_ID_PREFIX = "blk_"

# Structural extraction only. JavaScript rendering is out of scope (#64).
# Change-candidate typing is out of scope (#62). This module never writes
# Observations or Claims; generic_web remains discovery-only.

SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "iframe",
        "canvas",
        "object",
        "embed",
        "link",
        "meta",
        "head",
    }
)
VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
LIST_TAGS = frozenset({"ul", "ol", "dl"})
LIST_ITEM_TAGS = frozenset({"li", "dt", "dd"})
TABLE_TAGS = frozenset({"table"})
CODE_TAGS = frozenset({"pre"})
PARAGRAPH_TAGS = frozenset({"p", "blockquote", "figcaption"})
ALWAYS_BOILERPLATE_TAGS = frozenset({"nav", "aside", "menu"})
BANNER_TAGS = frozenset({"header", "footer"})
BOILERPLATE_ROLES = frozenset(
    {"navigation", "banner", "contentinfo", "complementary", "search"}
)
BOILERPLATE_TOKENS = frozenset(
    {
        "nav",
        "navbar",
        "navigation",
        "menu",
        "sidebar",
        "sidenav",
        "cookie",
        "consent",
        "advert",
        "ads",
        "promo",
        "social",
        "breadcrumb",
        "breadcrumbs",
        "share",
    }
)
MAIN_ROLES = frozenset({"main"})
MAIN_IDS = frozenset(
    {"content", "main", "main-content", "article", "document", "docs-content"}
)
MAIN_CLASSES = frozenset(
    {"markdown-body", "document", "main-content", "article-body", "prose"}
)
UNCERTAIN_MIN_SIMILARITY = 0.72
_TOKEN_RE = re.compile(r"[0-9A-Za-z\u3040-\u30ff\u3400-\u9fff]+")
_SLUG_RE = re.compile(r"[^\w]+", re.UNICODE)


class WebNormalizationError(ValueError):
    """Raised when HTML cannot be normalized into stable sections."""


class NormalizedDocumentImmutabilityError(ValueError):
    """Raised when a caller attempts to mutate a stored normalized document."""


@dataclass(frozen=True)
class SourceLocator:
    """Trace a normalized block back to raw snapshot bytes / DOM structure."""

    dom_path: str
    start_offset: int | None
    end_offset: int | None


@dataclass(frozen=True)
class NormalizedBlock:
    block_id: str
    kind: str
    text: str
    local_key: str
    locator: SourceLocator


@dataclass(frozen=True)
class NormalizedSection:
    section_id: str
    heading: str
    heading_level: int
    heading_path: tuple[str, ...]
    blocks: tuple[NormalizedBlock, ...]
    locator: SourceLocator


@dataclass(frozen=True)
class NormalizedDocument:
    document_id: str
    snapshot_id: str
    canonical_url: str
    content_hash: str
    normalizer_version: str
    title: str | None
    sections: tuple[NormalizedSection, ...]
    rejected: bool = False
    reject_reason: str | None = None

    @property
    def section_ids(self) -> tuple[str, ...]:
        return tuple(section.section_id for section in self.sections)


@dataclass(frozen=True)
class SectionAlignment:
    left_section_id: str | None
    right_section_id: str | None
    status: str
    confidence: float
    reason: str
    left_index: int | None = None
    right_index: int | None = None


@dataclass(frozen=True)
class DocumentAlignment:
    left_document_id: str
    right_document_id: str
    aligner_version: str
    canonical_url: str
    pairs: tuple[SectionAlignment, ...]
    rejected: bool = False
    reject_reason: str | None = None


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list[_Node | _Text]
    path: str
    inside_main: bool


@dataclass(frozen=True)
class _Text:
    text: str


@dataclass(frozen=True)
class _Emitted:
    kind: str
    text: str
    heading_level: int
    path: str


def generic_web_allows_claim_evidence() -> bool:
    """generic_web stays discovery-only even after HTML normalization."""
    return source_allows_claim_evidence(SourceKind.GENERIC_WEB.value)


def document_id_for(snapshot_id: str, *, normalizer_version: str = NORMALIZER_VERSION) -> str:
    material = f"{snapshot_id}\n{normalizer_version}"
    return f"{DOCUMENT_ID_PREFIX}{hashlib.sha256(material.encode()).hexdigest()}"


def section_id_for(
    *,
    canonical_url: str,
    heading: str,
    heading_level: int,
    heading_path: tuple[str, ...],
    occurrence: int = 0,
) -> str:
    """Stable across snapshots of the same URL. Independent of sibling order."""
    material = "\n".join(
        (
            canonical_url,
            str(heading_level),
            "\t".join(heading_path),
            _slug(heading),
            str(occurrence),
        )
    )
    return f"{SECTION_ID_PREFIX}{hashlib.sha256(material.encode()).hexdigest()}"


def block_id_for(*, section_id: str, local_key: str) -> str:
    material = f"{section_id}\n{local_key}"
    return f"{BLOCK_ID_PREFIX}{hashlib.sha256(material.encode()).hexdigest()}"


def normalize_web_snapshot(snapshot: WebSnapshot) -> NormalizedDocument:
    """Turn an immutable snapshot into a versioned normalized document.

    Never mutates ``snapshot.body`` or the snapshot store. Does not write
    Observations or Claims and does not render JavaScript.
    """
    body = bytes(snapshot.body)
    document_id = document_id_for(snapshot.snapshot_id)
    rejected = _rejected_document(snapshot, document_id, reason="empty_or_garbage_html")
    if not body or _looks_binary(body):
        return rejected

    raw = _decode_body(body, snapshot.header_map.get("content-type"))
    if raw is None:
        return rejected
    if not any(char.isalnum() for char in raw):
        return rejected

    title, emitted = _extract_structural_units(raw)
    located = _attach_offsets(raw, emitted)
    sections = _sections_from_units(snapshot.canonical_url, title, located)
    if not sections:
        return rejected
    if not any(
        any(char.isalnum() for char in block.text)
        for section in sections
        for block in section.blocks
    ):
        return rejected

    if body != snapshot.body:
        raise WebNormalizationError("normalizer must not mutate snapshot bytes")

    return NormalizedDocument(
        document_id=document_id,
        snapshot_id=snapshot.snapshot_id,
        canonical_url=snapshot.canonical_url,
        content_hash=snapshot.content_hash,
        normalizer_version=NORMALIZER_VERSION,
        title=title,
        sections=tuple(sections),
    )


def align_normalized_documents(
    left: NormalizedDocument,
    right: NormalizedDocument,
) -> DocumentAlignment:
    """Align sections between two normalized versions of the same URL.

    Exact section IDs match first. Insertion, deletion and reordering are
    recorded explicitly. Remaining leftovers may form an uncertain pair only
    when the match is unique and similar; otherwise they stay split.
    """
    if left.rejected or right.rejected:
        return DocumentAlignment(
            left_document_id=left.document_id,
            right_document_id=right.document_id,
            aligner_version=ALIGNER_VERSION,
            canonical_url=left.canonical_url,
            pairs=(),
            rejected=True,
            reject_reason="rejected_document",
        )
    if left.canonical_url != right.canonical_url:
        return DocumentAlignment(
            left_document_id=left.document_id,
            right_document_id=right.document_id,
            aligner_version=ALIGNER_VERSION,
            canonical_url=left.canonical_url,
            pairs=(),
            rejected=True,
            reject_reason="canonical_url_mismatch",
        )

    left_ids = list(left.section_ids)
    right_ids = list(right.section_ids)
    left_index = {section_id: index for index, section_id in enumerate(left_ids)}
    right_index = {section_id: index for index, section_id in enumerate(right_ids)}
    shared = [section_id for section_id in left_ids if section_id in right_index]

    left_matched_order = [section_id for section_id in left_ids if section_id in right_index]
    right_matched_order = [section_id for section_id in right_ids if section_id in left_index]
    reordered_ids = {
        section_id
        for index, section_id in enumerate(left_matched_order)
        if right_matched_order[index] != section_id
    } | {
        section_id
        for index, section_id in enumerate(right_matched_order)
        if left_matched_order[index] != section_id
    }

    pairs: list[SectionAlignment] = []
    used_left = set(shared)
    used_right = set(shared)
    for section_id in shared:
        moved = section_id in reordered_ids
        pairs.append(
            SectionAlignment(
                left_section_id=section_id,
                right_section_id=section_id,
                status="reordered" if moved else "matched",
                confidence=1.0,
                reason="stable_section_id" if not moved else "stable_section_id_reordered",
                left_index=left_index[section_id],
                right_index=right_index[section_id],
            )
        )

    leftover_left = [section for section in left.sections if section.section_id not in used_left]
    leftover_right = [section for section in right.sections if section.section_id not in used_right]
    uncertain_left: set[str] = set()
    uncertain_right: set[str] = set()
    for left_section in leftover_left:
        candidates: list[tuple[float, NormalizedSection]] = []
        for right_section in leftover_right:
            if right_section.section_id in uncertain_right:
                continue
            score = _section_similarity(left_section, right_section)
            if score >= UNCERTAIN_MIN_SIMILARITY:
                candidates.append((score, right_section))
        candidates.sort(key=lambda item: item[0], reverse=True)
        if len(candidates) != 1:
            continue
        score, right_section = candidates[0]
        reverse = [
            other
            for other in leftover_left
            if other.section_id not in uncertain_left
            and _section_similarity(other, right_section) >= UNCERTAIN_MIN_SIMILARITY
        ]
        if len(reverse) != 1:
            continue
        pairs.append(
            SectionAlignment(
                left_section_id=left_section.section_id,
                right_section_id=right_section.section_id,
                status="uncertain",
                confidence=round(score, 4),
                reason="unique_similar_leftover_not_merged",
                left_index=left_index[left_section.section_id],
                right_index=right_index[right_section.section_id],
            )
        )
        uncertain_left.add(left_section.section_id)
        uncertain_right.add(right_section.section_id)

    for section in leftover_left:
        if section.section_id in uncertain_left:
            continue
        pairs.append(
            SectionAlignment(
                left_section_id=section.section_id,
                right_section_id=None,
                status="deleted",
                confidence=1.0,
                reason="no_safe_alignment",
                left_index=left_index[section.section_id],
            )
        )
    for section in leftover_right:
        if section.section_id in uncertain_right:
            continue
        pairs.append(
            SectionAlignment(
                left_section_id=None,
                right_section_id=section.section_id,
                status="inserted",
                confidence=1.0,
                reason="no_safe_alignment",
                right_index=right_index[section.section_id],
            )
        )

    pairs.sort(
        key=lambda item: (
            item.left_index if item.left_index is not None else 10_000,
            item.right_index if item.right_index is not None else 10_000,
            item.status,
        )
    )
    return DocumentAlignment(
        left_document_id=left.document_id,
        right_document_id=right.document_id,
        aligner_version=ALIGNER_VERSION,
        canonical_url=left.canonical_url,
        pairs=tuple(pairs),
    )


def align_web_snapshots(left: WebSnapshot, right: WebSnapshot) -> DocumentAlignment:
    return align_normalized_documents(normalize_web_snapshot(left), normalize_web_snapshot(right))


class NormalizedDocumentStore:
    """File-backed immutable store. Never writes into a SnapshotStore directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, document: NormalizedDocument) -> NormalizedDocument:
        existing = self.get(document.document_id)
        if existing is not None:
            if existing != document:
                raise NormalizedDocumentImmutabilityError(
                    f"refusing to mutate stored document {document.document_id}"
                )
            return existing
        directory = self.root / document.document_id
        tmp = self.root / f".tmp-{document.document_id}-{secrets.token_hex(8)}"
        tmp.mkdir(parents=True, exist_ok=False)
        try:
            (tmp / "document.json").write_text(
                _encode_document(document),
                encoding="utf-8",
            )
            os.replace(tmp, directory)
        except Exception:
            _rmtree(tmp)
            raise
        return document

    def get(self, document_id: str) -> NormalizedDocument | None:
        path = self.root / document_id / "document.json"
        if not path.is_file():
            return None
        return _decode_document(json.loads(path.read_text(encoding="utf-8")))

    def get_for_snapshot(
        self,
        snapshot_id: str,
        *,
        normalizer_version: str = NORMALIZER_VERSION,
    ) -> NormalizedDocument | None:
        return self.get(document_id_for(snapshot_id, normalizer_version=normalizer_version))

    def list_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                path.name
                for path in self.root.iterdir()
                if path.is_dir() and path.name.startswith(DOCUMENT_ID_PREFIX)
            )
        )


def require_normalized_document(document: NormalizedDocument) -> NormalizedDocument:
    if document.rejected:
        raise WebNormalizationError(document.reject_reason or "empty_or_garbage_html")
    return document


def _rejected_document(snapshot: WebSnapshot, document_id: str, *, reason: str) -> NormalizedDocument:
    return NormalizedDocument(
        document_id=document_id,
        snapshot_id=snapshot.snapshot_id,
        canonical_url=snapshot.canonical_url,
        content_hash=snapshot.content_hash,
        normalizer_version=NORMALIZER_VERSION,
        title=None,
        sections=(),
        rejected=True,
        reject_reason=reason,
    )


def _looks_binary(body: bytes) -> bool:
    sample = body[:4096]
    if b"\x00" in sample:
        return True
    non_text = sum(1 for byte in sample if byte < 9 or (13 < byte < 32 and byte != 10))
    return bool(sample) and non_text / len(sample) > 0.30


def _decode_body(body: bytes, content_type: str | None) -> str | None:
    charset = _charset_from_content_type(content_type) or "utf-8"
    try:
        text = body.decode(charset)
    except (LookupError, UnicodeDecodeError):
        text = body.decode("utf-8", errors="replace")
    if text.count("\ufffd") > max(8, len(text) // 10):
        return None
    return text


def _charset_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    for part in content_type.split(";"):
        piece = part.strip()
        if piece.lower().startswith("charset="):
            value = piece.split("=", 1)[1].strip().strip("\"'")
            return value or None
    return None


def _extract_title(raw: str) -> str | None:
    match = re.search(r"<title\b[^>]*>(.*?)</title>", raw, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return _collapse_ws(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1)))) or None


def _extract_structural_units(raw: str) -> tuple[str | None, list[_Emitted]]:
    parser = _TreeBuilder()
    parser.feed(raw)
    parser.close()
    title = _collapse_ws(parser.title) or _extract_title(raw)
    roots = _main_roots(parser.root)
    emitted: list[_Emitted] = []
    for root in roots:
        _collect_units(root, emitted, inside_main=root.inside_main)
    return title, emitted


def _collect_units(node: _Node, emitted: list[_Emitted], *, inside_main: bool) -> None:
    if _is_boilerplate(node, inside_main=inside_main):
        return
    tag = node.tag
    if tag in HEADING_TAGS:
        text = _collapse_ws(_node_text(node))
        if text:
            emitted.append(_Emitted("heading", text, int(tag[1]), node.path))
        return
    if tag in LIST_TAGS:
        text = _list_text(node)
        if text:
            emitted.append(_Emitted("list", text, 0, node.path))
        return
    if tag in TABLE_TAGS:
        text = _table_text(node)
        if text:
            emitted.append(_Emitted("table", text, 0, node.path))
        return
    if tag in CODE_TAGS:
        text = _node_text(node, preserve_newlines=True).strip("\n")
        if _collapse_ws(text):
            emitted.append(_Emitted("code", text, 0, node.path))
        return
    if tag in PARAGRAPH_TAGS:
        text = _collapse_ws(_node_text(node))
        if text:
            emitted.append(_Emitted("paragraph", text, 0, node.path))
        return
    text_only = _direct_text_only(node)
    if text_only and not any(isinstance(child, _Node) for child in node.children):
        collapsed = _collapse_ws(text_only)
        if collapsed:
            emitted.append(_Emitted("paragraph", collapsed, 0, node.path))
        return
    next_main = inside_main or _is_main_container(node)
    for child in node.children:
        if isinstance(child, _Node):
            _collect_units(child, emitted, inside_main=next_main)
        elif inside_main or next_main:
            collapsed = _collapse_ws(child.text)
            if collapsed:
                emitted.append(_Emitted("paragraph", collapsed, 0, node.path))


@dataclass(frozen=True)
class _Located(_Emitted):
    start: int | None
    end: int | None


def _sections_from_units(
    canonical_url: str,
    title: str | None,
    units: list[_Located],
) -> list[NormalizedSection]:
    sections: list[NormalizedSection] = []
    current_heading = title or ""
    current_level = 0
    current_path: tuple[str, ...] = ("__lead__",) if current_heading else ("__lead__",)
    current_locator = SourceLocator("", None, None)
    current_blocks: list[_Emitted] = []
    started = False
    ancestors: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal current_blocks
        if not started and not current_blocks:
            current_blocks = []
            return
        if not current_blocks and current_level == 0 and not current_heading:
            current_blocks = []
            return
        heading = current_heading
        heading_path = current_path
        occurrence = sum(
            1
            for section in sections
            if section.heading_path == heading_path and section.heading_level == current_level
        )
        section_id = section_id_for(
            canonical_url=canonical_url,
            heading=heading,
            heading_level=current_level,
            heading_path=heading_path,
            occurrence=occurrence,
        )
        kind_counts: dict[str, int] = {}
        blocks: list[NormalizedBlock] = []
        if heading and current_level > 0:
            local_key = "heading:0"
            blocks.append(
                NormalizedBlock(
                    block_id=block_id_for(section_id=section_id, local_key=local_key),
                    kind="heading",
                    text=heading,
                    local_key=local_key,
                    locator=current_locator,
                )
            )
        for unit in current_blocks:
            index = kind_counts.get(unit.kind, 0)
            kind_counts[unit.kind] = index + 1
            local_key = f"{unit.kind}:{index}"
            blocks.append(
                NormalizedBlock(
                    block_id=block_id_for(section_id=section_id, local_key=local_key),
                    kind=unit.kind,
                    text=unit.text,
                    local_key=local_key,
                    locator=SourceLocator(unit.path, unit.start, unit.end)
                    if isinstance(unit, _Located)
                    else SourceLocator(unit.path, None, None),
                )
            )
        if not blocks:
            current_blocks = []
            return
        sections.append(
            NormalizedSection(
                section_id=section_id,
                heading=heading,
                heading_level=current_level,
                heading_path=heading_path,
                blocks=tuple(blocks),
                locator=current_locator,
            )
        )
        current_blocks = []

    for unit in units:
        if unit.kind == "heading":
            if started or current_blocks:
                flush()
            started = True
            current_heading = unit.text
            current_level = unit.heading_level
            ancestors = [(level, name) for level, name in ancestors if level < current_level]
            ancestors.append((current_level, _slug(unit.text)))
            current_path = tuple(name for _, name in ancestors)
            current_locator = (
                SourceLocator(unit.path, unit.start, unit.end)
                if isinstance(unit, _Located)
                else SourceLocator(unit.path, None, None)
            )
            current_blocks = []
            continue
        current_blocks.append(unit)
    flush()
    return sections


def _attach_offsets(raw: str, units: list[_Emitted]) -> list[_Located]:
    cursor = 0
    located: list[_Located] = []
    for unit in units:
        start, end = _find_in_raw(raw, unit.text, cursor)
        if start is not None:
            cursor = end or start
        located.append(_Located(unit.kind, unit.text, unit.heading_level, unit.path, start, end))
    return located


def _find_in_raw(raw: str, text: str, cursor: int) -> tuple[int | None, int | None]:
    variants = [text, html.escape(text, quote=False), html.escape(text)]
    first_line = text.split("\n", 1)[0]
    first_cell = first_line.split("\t", 1)[0].strip()
    if first_cell and first_cell not in variants:
        variants.append(first_cell)
        variants.append(html.escape(first_cell, quote=False))
    compact = _collapse_ws(text)
    if compact and compact not in variants:
        variants.append(compact)
    best: tuple[int, int] | None = None
    for variant in variants:
        index = raw.find(variant, cursor)
        if index == -1:
            collapsed = _find_collapsed(raw, _collapse_ws(variant), cursor)
            if collapsed is None:
                continue
            start, end = collapsed
        else:
            start, end = index, index + len(variant)
        if best is None or start < best[0]:
            best = (start, end)
    if best is None:
        return None, None
    return best


def _find_collapsed(raw: str, compact: str, cursor: int) -> tuple[int, int] | None:
    if not compact:
        return None
    first = compact.split(" ", 1)[0]
    index = raw.find(first, cursor)
    if index == -1:
        return None
    window = raw[index : index + min(len(raw) - index, max(len(compact) * 4, 64))]
    if compact not in _collapse_ws(html.unescape(window)):
        return None
    return index, index + len(window.strip())


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {}, [], "", False)
        self.stack = [self.root]
        self.title: str = ""
        self._in_title = False
        self._skip_depth = 0
        self._skip_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {key.lower(): (value or "") for key, value in attrs}
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in SKIP_TAGS:
            if tag not in VOID_TAGS:
                self._skip_depth = 1
                self._skip_tag = tag
            return
        parent = self.stack[-1]
        inside_main = parent.inside_main or _is_main_container_tag(tag, values)
        path = _child_path(parent, tag)
        node = _Node(tag, values, [], path, inside_main)
        parent.children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._in_title and tag == "title":
            self._in_title = False
            return
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._skip_tag = None
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS and tag.lower() not in SKIP_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip_depth:
            return
        if data:
            self.stack[-1].children.append(_Text(data))


def _child_path(parent: _Node, tag: str) -> str:
    index = sum(1 for child in parent.children if isinstance(child, _Node) and child.tag == tag) + 1
    prefix = parent.path or ""
    return f"{prefix}/{tag}[{index}]"


def _main_roots(root: _Node) -> list[_Node]:
    found: list[_Node] = []

    def walk(node: _Node) -> None:
        if _is_main_container(node):
            found.append(node)
            return
        for child in node.children:
            if isinstance(child, _Node):
                walk(child)

    walk(root)
    return found or [root]


def _is_main_container(node: _Node) -> bool:
    return _is_main_container_tag(node.tag, node.attrs)


def _is_main_container_tag(tag: str, attrs: dict[str, str]) -> bool:
    if tag in {"main", "article"}:
        return True
    if attrs.get("role", "").casefold() in MAIN_ROLES:
        return True
    if attrs.get("id", "").casefold() in MAIN_IDS:
        return True
    classes = set(_tokens(attrs.get("class", "")))
    return bool(classes & MAIN_CLASSES)


def _is_boilerplate(node: _Node, *, inside_main: bool) -> bool:
    tag = node.tag
    role = node.attrs.get("role", "").casefold()
    if tag in ALWAYS_BOILERPLATE_TAGS or role in BOILERPLATE_ROLES:
        return True
    if node.attrs.get("hidden") is not None or node.attrs.get("aria-hidden", "").casefold() == "true":
        return True
    if tag in BANNER_TAGS and not inside_main:
        return True
    tokens = _attr_tokens(node.attrs)
    if not inside_main and tokens & {"header", "footer"}:
        return True
    return bool(tokens & BOILERPLATE_TOKENS)


def _attr_tokens(attrs: dict[str, str]) -> set[str]:
    parts = [attrs.get("id", ""), attrs.get("class", "")]
    tokens: set[str] = set()
    for part in parts:
        tokens.update(_tokens(part.replace("-", " ").replace("_", " ")))
    return tokens


def _tokens(value: str) -> set[str]:
    return {piece.casefold() for piece in re.split(r"[^\w]+", value) if piece}


def _node_text(node: _Node, *, preserve_newlines: bool = False) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, _Text):
            parts.append(child.text)
        elif child.tag not in SKIP_TAGS:
            parts.append(_node_text(child, preserve_newlines=preserve_newlines))
    joined = "".join(parts)
    return joined if preserve_newlines else joined


def _direct_text_only(node: _Node) -> str:
    return "".join(child.text for child in node.children if isinstance(child, _Text))


def _list_text(node: _Node) -> str:
    items: list[str] = []
    for child in node.children:
        if isinstance(child, _Node) and child.tag in LIST_ITEM_TAGS:
            text = _collapse_ws(_node_text(child))
            if text:
                items.append(text)
        elif isinstance(child, _Node) and child.tag in LIST_TAGS:
            nested = _list_text(child)
            if nested:
                items.append(nested)
    return "\n".join(items)


def _table_text(node: _Node) -> str:
    rows: list[str] = []
    for row in _find_rows(node):
        cells = [
            _collapse_ws(_node_text(cell))
            for cell in row.children
            if isinstance(cell, _Node) and cell.tag in {"th", "td"}
        ]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append("\t".join(cells))
    return "\n".join(rows)


def _find_rows(node: _Node) -> list[_Node]:
    rows: list[_Node] = []
    if node.tag == "tr":
        return [node]
    for child in node.children:
        if isinstance(child, _Node):
            rows.extend(_find_rows(child))
    return rows


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _slug(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    slug = _SLUG_RE.sub("-", folded).strip("-")
    return slug or "__empty__"


def _section_similarity(left: NormalizedSection, right: NormalizedSection) -> float:
    left_tokens = _content_tokens(left)
    right_tokens = _content_tokens(right)
    if not left_tokens and not right_tokens:
        return 0.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _content_tokens(section: NormalizedSection) -> frozenset[str]:
    texts = [block.text for block in section.blocks if block.kind != "heading"]
    if not texts:
        texts = [section.heading]
    return frozenset(_TOKEN_RE.findall(unicodedata.normalize("NFKC", " ".join(texts)).casefold()))


def _encode_document(document: NormalizedDocument) -> str:
    payload = {
        "document_id": document.document_id,
        "snapshot_id": document.snapshot_id,
        "canonical_url": document.canonical_url,
        "content_hash": document.content_hash,
        "normalizer_version": document.normalizer_version,
        "title": document.title,
        "rejected": document.rejected,
        "reject_reason": document.reject_reason,
        "sections": [
            {
                "section_id": section.section_id,
                "heading": section.heading,
                "heading_level": section.heading_level,
                "heading_path": list(section.heading_path),
                "locator": _encode_locator(section.locator),
                "blocks": [
                    {
                        "block_id": block.block_id,
                        "kind": block.kind,
                        "text": block.text,
                        "local_key": block.local_key,
                        "locator": _encode_locator(block.locator),
                    }
                    for block in section.blocks
                ],
            }
            for section in document.sections
        ],
    }
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _encode_locator(locator: SourceLocator) -> dict[str, Any]:
    return {
        "dom_path": locator.dom_path,
        "start_offset": locator.start_offset,
        "end_offset": locator.end_offset,
    }


def _decode_document(payload: dict[str, Any]) -> NormalizedDocument:
    sections = []
    for raw in payload.get("sections", []):
        blocks = tuple(
            NormalizedBlock(
                block_id=str(block["block_id"]),
                kind=str(block["kind"]),
                text=str(block["text"]),
                local_key=str(block["local_key"]),
                locator=_decode_locator(block["locator"]),
            )
            for block in raw.get("blocks", [])
        )
        sections.append(
            NormalizedSection(
                section_id=str(raw["section_id"]),
                heading=str(raw["heading"]),
                heading_level=int(raw["heading_level"]),
                heading_path=tuple(str(item) for item in raw.get("heading_path", ())),
                blocks=blocks,
                locator=_decode_locator(raw["locator"]),
            )
        )
    return NormalizedDocument(
        document_id=str(payload["document_id"]),
        snapshot_id=str(payload["snapshot_id"]),
        canonical_url=str(payload["canonical_url"]),
        content_hash=str(payload["content_hash"]),
        normalizer_version=str(payload["normalizer_version"]),
        title=payload.get("title"),
        sections=tuple(sections),
        rejected=bool(payload.get("rejected", False)),
        reject_reason=payload.get("reject_reason"),
    )


def _decode_locator(payload: dict[str, Any]) -> SourceLocator:
    return SourceLocator(
        dom_path=str(payload.get("dom_path", "")),
        start_offset=payload.get("start_offset"),
        end_offset=payload.get("end_offset"),
    )


def _rmtree(path: Path) -> None:
    if not path.exists():
        return
    if path.is_file():
        path.unlink()
        return
    for child in path.iterdir():
        _rmtree(child)
    path.rmdir()
