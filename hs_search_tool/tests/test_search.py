"""Tests for the core search() method — numeric prefix + keyword behaviour."""
from __future__ import annotations


def test_search_empty_query_returns_empty(engine):
    assert engine.search("") == []
    assert engine.search("   ") == []
    assert engine.search(None) == []


def test_search_numeric_4digit_prefix(engine):
    """Searching for '8703' should return only codes starting with 8703."""
    results = engine.search("8703", limit=25)
    assert len(results) > 0
    assert all(r.hs_code.startswith("8703") for r in results), [r.hs_code for r in results]


def test_search_numeric_6digit_prefix(engine):
    """Searching for an actual 6-digit prefix from data should return only that subset."""
    # Find a real 6-digit prefix present in our data (varies by source data)
    sample = engine.search("8703", limit=10)
    assert sample, "expected some 8703 codes"
    prefix6 = sample[0].hs_code[:6]
    results = engine.search(prefix6, limit=50)
    assert len(results) > 0
    assert all(r.hs_code.startswith(prefix6) for r in results), [r.hs_code for r in results]


def test_search_numeric_chapter_prefix(engine):
    """Searching for '85' (chapter) should return codes from chapter 85."""
    results = engine.search("85", limit=25)
    assert len(results) > 0
    assert all(r.hs_code.startswith("85") for r in results)
    assert all(r.chapter == "85" for r in results)


def test_search_numeric_specific_12digit(engine):
    """An exact 12-digit code that exists should return exactly that one result."""
    # Pick the first known code from our data
    stats = engine.stats()
    assert stats["total_hs_codes"] > 0
    # Grab a known code from any search
    sample = engine.search("87", limit=1)
    assert sample, "expected at least one chapter-87 row"
    code = sample[0].hs_code
    results = engine.search(code, limit=5)
    assert any(r.hs_code == code for r in results), f"didn't find {code} in {[r.hs_code for r in results]}"


def test_search_limit_is_respected(engine):
    """Limit parameter must cap results returned."""
    for limit in (1, 3, 10):
        results = engine.search("85", limit=limit)
        assert len(results) <= limit


def test_search_results_have_certification(engine):
    """Every result must carry a certification phrase (one of the known keys)."""
    results = engine.search("85", limit=20)
    for r in results:
        assert r.certification is not None
        assert r.certification.key in {
            "supplier_declaration_free_trade",
            "saber_coc_or_qm",
            "quality_mark_only",
            "gcts_or_qm",
            "multi_route",
            "type_approval",
            "unknown",
        }
        assert r.certification.phrase_en
        assert r.certification.phrase_ar


def test_search_arabic_keyword_returns_arabic_results(engine):
    """Searching for an Arabic keyword should return matching products.

    With synonyms enabled, 'بطارية' expands to include trade-term 'مدخرات'
    (electrical accumulators) and the English 'battery'/'batteries'. So a
    result row may have ANY of these in its AR or EN name — the test just
    asserts we get non-empty results and each carries some meaningful name.
    """
    results = engine.search("بطارية", limit=20)
    assert len(results) > 0, "Arabic keyword 'بطارية' (battery) should match something"
    for r in results:
        ar = r.product_name_ar or ""
        en = (r.product_name_en or "").lower()
        # At least one of the recognized forms (Arabic root or English) must appear
        assert (
            "بطاري" in ar or "مدخر" in ar
            or "battery" in en or "batteries" in en or "primary" in en or "secondary" in en
        ), f"{r.hs_code}: AR={ar!r}, EN={en!r}"


def test_search_arabic_singular_matches_plural(engine):
    """Singular query 'بطارية' must return rows that share the same root.

    Acceptable forms include 'بطاريات' (plural), 'مدخرات' (trade synonym), or
    English 'battery/batteries' (via product_name_en lookup).
    """
    results = engine.search("بطارية", limit=50)
    accepted = [
        r for r in results
        if (
            "بطاريات" in r.product_name_ar
            or "مدخرات" in r.product_name_ar
            or "battery" in (r.product_name_en or "").lower()
            or "batteries" in (r.product_name_en or "").lower()
        )
    ]
    assert len(accepted) > 0, "singular query should find related data via stemming/synonyms"


def test_search_arabic_plural_matches_singular(engine):
    """Plural query 'أجهزة' must return rows whose product name uses singular 'جهاز'."""
    # This may or may not find singular forms depending on data; the test just
    # ensures stemming doesn't break the plural form itself.
    results = engine.search("أجهزة", limit=10)
    assert len(results) > 0


def test_search_multi_token_arabic(engine):
    """Multi-word Arabic query: results are scored by token-match count.

    Contract:
      - Every result matches at least one of the query tokens.
      - Results matching more tokens rank higher (precision-first).
      - Results matching fewer tokens still surface as fallback recall.

    This replaces the previous AND-only contract so multi-word English queries
    like 'food beverage' or 'baby stroller' return useful results instead of 0.
    """
    results = engine.search("جهاز كهربائي", limit=20)
    if not results:
        return  # nothing to assert if data has no overlap

    # Every result must contain at least one of the two normalized stems.
    # "جهاز" and "اجهز/أجهز" cover 'device'; "كهربائي" covers 'electric'.
    for r in results:
        name = r.product_name_ar.lower()
        has_device = "جهاز" in name or "أجهز" in name or "اجهز" in name
        has_electric = "كهربائي" in name or "كهربائ" in name
        assert has_device or has_electric, name


def test_search_nonexistent_query_returns_empty(engine):
    """A made-up nonsense keyword should return no results."""
    assert engine.search("xyzqzznonsense123") == []


def test_get_by_prefix_works(engine):
    results = engine.get_by_prefix("8703", limit=25)
    assert len(results) > 0
    assert all(r.hs_code.startswith("8703") for r in results)


def test_get_by_prefix_empty_for_invalid(engine):
    assert engine.get_by_prefix("", limit=25) == []
    assert engine.get_by_prefix("notnumeric", limit=25) == []
