"""Quote-text anchor resolution — algorithm G, normative per docs/workspace §3a.

v1 adaptation to the SQLite stack: no block-index yet, so a resolution carries
absolute offsets into the document's canonical markdown plus a content_hash
(used later for drift detection). block_ref is deferred.

Fuzzy v1 limitation: only whitespace-flexible matching (offsets stay exact).
NFKC + diacritic-strip is intentionally NOT applied because it changes string
length and would invalidate offsets; revisit when the block-index lands.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Resolution:
    absolute_start: int
    absolute_end: int
    content_hash: str


class AnchorNotFound(Exception):
    """Raised when a selector cannot be resolved to exactly one range."""

    def __init__(self, reason: str, candidates: list[dict]):
        self.reason = reason            # "quote_not_found" | "ambiguous"
        self.candidates = candidates
        super().__init__(f"anchor not found: {reason}")


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _find_all(haystack: str, needle: str) -> list[tuple[int, int]]:
    """All non-overlapping exact occurrences as (start, end)."""
    if not needle:
        return []
    out: list[tuple[int, int]] = []
    i = haystack.find(needle)
    while i != -1:
        out.append((i, i + len(needle)))
        i = haystack.find(needle, i + len(needle))
    return out


def _find_all_fuzzy(haystack: str, needle: str) -> list[tuple[int, int]]:
    """Whitespace-flexible occurrences (runs of WS in the quote match \\s+)."""
    tokens = needle.split()
    if not tokens:
        return []
    pattern = r"\s+".join(re.escape(tok) for tok in tokens)
    return [(m.start(), m.end()) for m in re.finditer(pattern, haystack)]


def resolve_anchor(selector: dict, markdown: str) -> Resolution:
    """Resolve a quote selector against canonical markdown. See spec §3a."""
    quote: str = selector["quote"]
    prefix: str = selector.get("prefix") or ""
    suffix: str = selector.get("suffix") or ""
    occurrence = selector.get("occurrence")  # 1-based, optional
    fuzzy: bool = selector.get("fuzzy", False)

    # Step 1: all exact occurrences (fuzzy fallback only if opted in).
    matches = _find_all(markdown, quote)
    if not matches and fuzzy:
        matches = _find_all_fuzzy(markdown, quote)
    if not matches:
        raise AnchorNotFound("quote_not_found", [])

    # Step 2: narrow by prefix/suffix — only if the filter is non-empty.
    if prefix or suffix:
        filtered = [
            (s, e)
            for (s, e) in matches
            if (not prefix or markdown[max(0, s - len(prefix)):s].endswith(prefix))
            and (not suffix or markdown[e:e + len(suffix)].startswith(suffix))
        ]
        if filtered:
            matches = filtered

    # Step 3: occurrence is applied AFTER prefix/suffix narrowing (spec note).
    if len(matches) > 1 and occurrence is not None:
        if 1 <= occurrence <= len(matches):
            matches = [matches[occurrence - 1]]

    # Step 4: exactly one → resolved.
    if len(matches) == 1:
        s, e = matches[0]
        return Resolution(absolute_start=s, absolute_end=e, content_hash=_sha256(quote))

    # Step 5: still ambiguous → candidates (capped at 10).
    raise AnchorNotFound(
        "ambiguous",
        [{"absolute_start": s, "absolute_end": e} for (s, e) in matches[:10]],
    )
