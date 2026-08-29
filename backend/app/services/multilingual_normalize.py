from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

LanguageTag = Literal["ja", "en", "mixed", "unknown"]
NORMALIZER_VERSION = "multilingual-normalize-v1"

_CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)
_GHSA_RE = re.compile(r"GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}", re.IGNORECASE)
_PACKAGE_RE = re.compile(
    r"@[a-z0-9][\w.-]*/[a-z0-9][\w.-]*|[a-z][a-z0-9_.-]+/[a-z0-9][a-z0-9_.-]+",
    re.IGNORECASE,
)
_VERSION_RE = re.compile(r"v?\d+(?:\.\d+){1,3}(?:[-+][a-z0-9.-]+)?", re.IGNORECASE)
_JP_YMD_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_JP_YM_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月")
_SLASH_DATE_RE = re.compile(r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b")
_JP_PUNCT_RE = re.compile(r"[。、．，！？；：｢｣「」『』（）()【】［］\[\]〈〉《》・…‥〜～]")
_PLACEHOLDER_RE = re.compile(r"\x00ID(\d+)\x00")
_SYMBOL_TOKENS = (">=", "<=", "!=", "==")
_COMPARATOR_CHARS = {
    "≦": "<=",
    "≤": "<=",
    "≧": ">=",
    "≥": ">=",
    "≠": "!=",
}

# Longest-match terms. Empty replacement drops function words.
_LEXICON: dict[str, str] = {
    "未対応": "not supported",
    "非対応": "not supported",
    "未サポート": "not supported",
    "非サポート": "not supported",
    "サポートされていません": "support not",
    "サポートされていない": "support not",
    "サポートされない": "support not",
    "されていません": "not",
    "されていない": "not",
    "されない": "not",
    "していない": "not",
    "しません": "not",
    "しない": "not",
    "ありません": "not",
    "いません": "not",
    "なかった": "not",
    "ません": "not",
    "なく": "not",
    "なし": "not",
    "ない": "not",
    "ずに": "not",
    "以上": ">=",
    "以降": ">=",
    "以後": ">=",
    "以下": "<=",
    "以内": "<=",
    "未満": "<",
    "超過": ">",
    "ワークフロー": "workflow",
    "性能低下": "degradation",
    "利用可能": "available",
    "利用不可": "not available",
    "非推奨": "deprecated",
    "無制限": "unbounded",
    "受け入れ": "accept",
    "脆弱性": "vulnerability",
    "サポート": "support",
    "デプロイ": "deploy",
    "クッキー": "cookie",
    "インシデント": "incident",
    "バージョン": "version",
    "パッケージ": "package",
    "リリース": "release",
    "アップデート": "update",
    "セキュリティ": "security",
    "緩和済み": "mitigate",
    "対応": "supported",
    "失敗": "fail",
    "起動": "start",
    "終了": "end",
    "緩和": "mitigate",
    "低下": "degradation",
    "遅延": "delay",
    "応答": "response",
    "影響": "affect",
    "修正": "fix",
    "更新": "update",
    "公開": "publish",
    "廃止": "removed",
    "開始": "start",
    "停止": "stop",
    "障害": "incident",
    "復旧": "recover",
    "調査": "investigate",
    "監視": "monitor",
    "解決": "resolve",
    "特定": "identify",
    "対象": "affected",
    "しています": "",
    "している": "",
    "されました": "",
    "されている": "",
    "されて": "",
    "される": "",
    "しました": "",
    "します": "",
    "でした": "",
    "である": "",
    "なります": "",
    "なりました": "",
    "です": "",
    "ます": "",
    "した": "",
    "して": "",
    "いる": "",
    "から": "",
    "まで": "",
    "より": "",
    "など": "",
    "これ": "",
    "それ": "",
    "この": "",
    "その": "",
    "あの": "",
    "の": "",
    "は": "",
    "が": "",
    "を": "",
    "に": "",
    "で": "",
    "と": "",
    "も": "",
    "へ": "",
    "や": "",
    "だ": "",
}
_MAX_LEXEME = max(len(term) for term in _LEXICON)
_PREFIX_NEGATION = frozenset("未非")


@dataclass(frozen=True)
class MultilingualNormalized:
    language: LanguageTag
    text: str
    tokens: tuple[str, ...]
    identifiers: tuple[str, ...]
    fallback: bool
    version: str = NORMALIZER_VERSION


def detect_language(text: str) -> LanguageTag:
    normalized = unicodedata.normalize("NFKC", text or "")
    if not any(char.isalnum() for char in normalized):
        return "unknown"

    cjk = 0
    latin = 0
    for char in normalized:
        if _is_cjk(char):
            cjk += 1
        elif char.isascii() and char.isalpha():
            latin += 1

    if cjk == 0 and latin == 0:
        return "unknown"
    if cjk == 0:
        return "en"
    # Japanese technical prose often embeds Latin product/status tokens.
    # Treat CJK-bearing sentences as ja unless the CJK span is only incidental.
    if latin == 0 or cjk >= 6 or cjk >= latin:
        return "ja"
    if cjk <= 2 and latin >= 12:
        return "en"
    return "mixed"


def pair_language(*texts: str) -> LanguageTag:
    tags = {detect_language(text) for text in texts}
    if tags == {"en"}:
        return "en"
    if tags == {"ja"}:
        return "ja"
    if tags <= {"unknown"}:
        return "unknown"
    return "mixed"


def extract_identifiers(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", text or "")
    found: list[str] = []
    seen: set[str] = set()
    for pattern in (_GHSA_RE, _CVE_RE, _PACKAGE_RE, _VERSION_RE):
        for match in pattern.findall(normalized):
            key = match.casefold()
            if key not in seen:
                seen.add(key)
                found.append(match)
    return tuple(found)


def normalize_multilingual(text: str) -> MultilingualNormalized:
    language = detect_language(text)
    fallback = language == "unknown"
    prepared = prepare_for_english_canonicalize(text)
    tokens = tuple(token for token in prepared.split() if token)
    return MultilingualNormalized(
        language=language,
        text=prepared,
        tokens=tokens,
        identifiers=extract_identifiers(text),
        fallback=fallback,
    )


def prepare_for_english_canonicalize(text: str) -> str:
    """Meaning-preserving rewrite so English whitespace tokenization can run.

    English-only input stays NFKC-stable. Japanese/mixed/unknown input is
    segmented with a CJK-aware lexicon and technical IDs are held intact.
    """
    if not text:
        return text
    normalized = unicodedata.normalize("NFKC", text)
    language = detect_language(normalized)
    if language == "en":
        return normalized
    return _normalize_non_english(normalized)


def metrics_by_language(
    rows: Sequence[tuple[str, str, bool, bool]],
) -> dict[LanguageTag, dict[str, float | int]]:
    """Report equivalence precision/recall sliced by ja / en / mixed / unknown."""
    buckets: dict[LanguageTag, list[tuple[bool, bool]]] = {
        "ja": [],
        "en": [],
        "mixed": [],
        "unknown": [],
    }
    fallbacks: dict[LanguageTag, int] = {key: 0 for key in buckets}
    for prior, candidate, expected, predicted in rows:
        language = pair_language(prior, candidate)
        buckets[language].append((expected, predicted))
        if detect_language(prior) == "unknown" or detect_language(candidate) == "unknown":
            fallbacks[language] += 1
    report: dict[LanguageTag, dict[str, float | int]] = {}
    for language, pairs in buckets.items():
        true_positive = sum(want and got for want, got in pairs)
        predicted_positive = sum(got for _, got in pairs)
        actual_positive = sum(want for want, _ in pairs)
        report[language] = {
            "pair_count": len(pairs),
            "fallback_count": fallbacks[language],
            "precision": (true_positive / predicted_positive) if predicted_positive else 1.0,
            "recall": (true_positive / actual_positive) if actual_positive else 1.0,
        }
    return report


def _normalize_non_english(text: str) -> str:
    protected, inventory = _protect_identifiers(text)
    rewritten = _normalize_dates(protected)
    rewritten = re.sub(r"(?<=\d),(?=\d)", "", rewritten)
    for source, replacement in _COMPARATOR_CHARS.items():
        rewritten = rewritten.replace(source, f" {replacement} ")
    rewritten = _JP_PUNCT_RE.sub(" ", rewritten)
    tokens = _segment(rewritten)
    restored = [_restore_placeholders(token, inventory) for token in tokens]
    return " ".join(token for token in restored if token)


def _protect_identifiers(text: str) -> tuple[str, tuple[str, ...]]:
    inventory: list[str] = []

    def stash(match: re.Match[str]) -> str:
        inventory.append(match.group(0))
        return f"\x00ID{len(inventory) - 1}\x00"

    rewritten = text
    for pattern in (_GHSA_RE, _CVE_RE, _PACKAGE_RE, _VERSION_RE):
        rewritten = pattern.sub(stash, rewritten)
    return rewritten, tuple(inventory)


def _restore_placeholders(token: str, inventory: Sequence[str]) -> str:
    def restore(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return inventory[index] if 0 <= index < len(inventory) else match.group(0)

    return _PLACEHOLDER_RE.sub(restore, token)


def _normalize_dates(text: str) -> str:
    def ymd(match: re.Match[str]) -> str:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"

    rewritten = _JP_YMD_RE.sub(ymd, text)
    rewritten = _SLASH_DATE_RE.sub(ymd, rewritten)
    rewritten = _JP_YM_RE.sub(
        lambda match: f"{int(match.group(1)):04d}-{int(match.group(2)):02d}",
        rewritten,
    )
    return rewritten


def _segment(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        symbol = _match_symbol(text, index)
        if symbol is not None:
            tokens.append(symbol)
            index += len(symbol)
            continue
        if _is_placeholder_start(text, index):
            end = text.find("\x00", index + 1)
            end = length if end < 0 else end + 1
            tokens.append(text[index:end])
            index = end
            continue
        if _is_ascii_ident_char(char):
            end = index + 1
            while end < length and _is_ascii_ident_char(text[end]):
                end += 1
            while end > index and text[end - 1] in "._/-":
                end -= 1
            if end == index:
                index += 1
                continue
            tokens.append(text[index:end])
            index = end
            continue
        if _is_cjk(char):
            tokens.extend(_segment_cjk(text, index))
            index = _consume_cjk_run(text, index)
            continue
        index += 1
    return tokens


def _segment_cjk(text: str, start: int) -> list[str]:
    run_end = _consume_cjk_run(text, start)
    run = text[start:run_end]
    emitted: list[str] = []
    index = 0
    pending = ""
    while index < len(run):
        replacement, consumed = _lex_match(run, index)
        if consumed:
            if pending:
                emitted.append(pending)
                pending = ""
            if replacement:
                emitted.extend(part for part in replacement.split() if part)
            index += consumed
            continue
        pending += run[index]
        index += 1
    if pending:
        emitted.append(pending)
    return emitted


def _lex_match(run: str, start: int) -> tuple[str | None, int]:
    limit = min(_MAX_LEXEME, len(run) - start)
    for size in range(limit, 0, -1):
        piece = run[start : start + size]
        if piece in _LEXICON:
            return _LEXICON[piece], size
    if run[start] in _PREFIX_NEGATION:
        for size in range(min(_MAX_LEXEME, len(run) - start - 1), 0, -1):
            rest = run[start + 1 : start + 1 + size]
            if rest in _LEXICON and _LEXICON[rest]:
                return f"not {_LEXICON[rest]}", size + 1
    return None, 0


def _consume_cjk_run(text: str, start: int) -> int:
    end = start
    while end < len(text) and _is_cjk(text[end]):
        end += 1
    return end


def _match_symbol(text: str, index: int) -> str | None:
    for symbol in _SYMBOL_TOKENS:
        if text.startswith(symbol, index):
            return symbol
    char = text[index]
    if char in "<>":
        return char
    return None


def _is_placeholder_start(text: str, index: int) -> bool:
    return text.startswith("\x00ID", index)


def _is_ascii_ident_char(char: str) -> bool:
    return char.isascii() and (char.isalnum() or char in "._/-")


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x3040 <= code <= 0x30FF
        or 0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0xFF66 <= code <= 0xFF9D
    )
