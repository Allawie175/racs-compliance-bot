"""Tests for English keyword search + product_name_en exposure."""
from __future__ import annotations


def test_english_keyword_finds_results(engine):
    """An English term that appears in hs_code_regulations.csv should now match."""
    results = engine.search("battery", limit=20)
    assert len(results) > 0, "English 'battery' should match codes that have EN product names"


def test_english_keyword_returns_codes_with_en_name(engine):
    """Results from an English search should expose product_name_en."""
    results = engine.search("battery", limit=5)
    for r in results:
        # At least the EN name should be populated for matches found via EN
        assert r.product_name_en, f"missing EN name for {r.hs_code}: {r.to_dict()}"
        assert "battery" in r.product_name_en.lower() or "batteries" in r.product_name_en.lower()


def test_arabic_search_still_works(engine):
    """Adding EN search must not break Arabic search."""
    results = engine.search("بطارية", limit=10)
    assert len(results) > 0


def test_search_result_includes_product_name_en_field(engine):
    """Every SearchResult must carry product_name_en (string or None)."""
    results = engine.search("8703", limit=5)
    for r in results:
        # Field exists and is either a string or None
        assert hasattr(r, "product_name_en")
        assert r.product_name_en is None or isinstance(r.product_name_en, str)


def test_product_detail_includes_product_name_en(engine):
    """ProductDetail must also expose product_name_en."""
    sample = engine.search("8703", limit=1)
    assert sample
    detail = engine.get_details(sample[0].hs_code)
    assert hasattr(detail, "product_name_en")
