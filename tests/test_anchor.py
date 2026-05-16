"""Anchor resolution algorithm G — normative per docs/workspace spec §3a.

v1 adaptation: SQLite stack has no block-index, so resolution returns absolute
offsets into content_md + a content_hash (block_ref deferred).
"""

import hashlib

import pytest

from src.workspace.anchor import AnchorNotFound, resolve_anchor

MD = "alpha beta gamma. The quick brown fox. alpha beta delta. The quick brown cat."


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class TestUniqueMatch:
    def test_single_occurrence_resolves(self):
        r = resolve_anchor({"quote": "quick brown fox"}, MD)
        assert MD[r.absolute_start:r.absolute_end] == "quick brown fox"
        assert r.content_hash == _sha("quick brown fox")

    def test_quote_not_found_raises(self):
        with pytest.raises(AnchorNotFound) as e:
            resolve_anchor({"quote": "nonexistent text"}, MD)
        assert e.value.reason == "quote_not_found"
        assert e.value.candidates == []


class TestDisambiguation:
    def test_prefix_narrows_to_one(self):
        # "alpha beta" appears twice; prefix before the 2nd is "gamma. The quick brown fox. "
        r = resolve_anchor(
            {"quote": "alpha beta", "suffix": " delta"}, MD
        )
        assert MD[r.absolute_start:r.absolute_end] == "alpha beta"
        assert MD[r.absolute_end:r.absolute_end + 6] == " delta"

    def test_prefix_filter_empty_falls_back_to_all(self):
        # Spec: only narrow if the prefix/suffix filter yields a non-empty set.
        # Non-matching suffix → fall back → still ambiguous → AnchorNotFound.
        with pytest.raises(AnchorNotFound) as e:
            resolve_anchor({"quote": "alpha beta", "suffix": " ZZZ"}, MD)
        assert e.value.reason == "ambiguous"

    def test_occurrence_after_narrowing(self):
        # "The quick brown" twice; occurrence picks among them (post prefix/suffix).
        r = resolve_anchor({"quote": "The quick brown", "occurrence": 2}, MD)
        assert r.absolute_start == MD.rindex("The quick brown")

    def test_ambiguous_returns_candidates_capped(self):
        many = " ".join(["foo"] * 25)
        with pytest.raises(AnchorNotFound) as e:
            resolve_anchor({"quote": "foo"}, many)
        assert e.value.reason == "ambiguous"
        assert len(e.value.candidates) == 10  # capped per spec
        assert all("absolute_start" in c for c in e.value.candidates)


class TestFuzzy:
    def test_fuzzy_opt_in_only(self):
        # default fuzzy=False: whitespace-collapsed variant not found
        with pytest.raises(AnchorNotFound):
            resolve_anchor({"quote": "quick   brown   fox"}, MD)

    def test_fuzzy_true_collapses_ws(self):
        r = resolve_anchor({"quote": "quick   brown   fox", "fuzzy": True}, MD)
        assert MD[r.absolute_start:r.absolute_end].replace(" ", "") == "quickbrownfox"
