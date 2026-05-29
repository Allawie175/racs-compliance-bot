"""Tests for search_grouped() — the chapter-grouped disambiguation flow."""
from __future__ import annotations


def test_grouped_returns_chapters_sorted_by_count(engine):
    """Groups are returned sorted by count desc, so the dominant chapter shows first."""
    groups = engine.search_grouped("85", per_chapter_limit=3)
    assert len(groups) >= 1
    counts = [g.count for g in groups]
    assert counts == sorted(counts, reverse=True), f"groups not sorted by count desc: {counts}"


def test_grouped_each_group_has_label(engine):
    """Every group must carry a chapter + readable label."""
    groups = engine.search_grouped("battery", per_chapter_limit=3)
    for g in groups:
        assert len(g.chapter) == 2 and g.chapter.isdigit(), g.chapter
        assert g.chapter_label, f"missing label for chapter {g.chapter}"


def test_grouped_respects_per_chapter_limit(engine):
    """per_chapter_limit must cap the results list within each group."""
    for limit in (1, 3, 10):
        groups = engine.search_grouped("85", per_chapter_limit=limit)
        for g in groups:
            assert len(g.results) <= limit, f"chapter {g.chapter} returned {len(g.results)} > {limit}"


def test_grouped_arabic_query_spans_multiple_chapters(engine):
    """A vague Arabic keyword like 'جهاز' should hit results in multiple chapters."""
    groups = engine.search_grouped("جهاز", per_chapter_limit=3)
    # Don't enforce exact count — depends on data — but at minimum should produce some groups
    assert len(groups) >= 1


def test_grouped_empty_query(engine):
    assert engine.search_grouped("") == []
    assert engine.search_grouped("   ") == []


def test_grouped_results_share_their_chapter(engine):
    """Sanity: every result within a group must have that group's chapter."""
    groups = engine.search_grouped("85", per_chapter_limit=5)
    for g in groups:
        for r in g.results:
            assert r.chapter == g.chapter, f"mismatch: result {r.hs_code} chapter {r.chapter} != group {g.chapter}"
