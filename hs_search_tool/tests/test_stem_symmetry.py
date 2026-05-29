"""Regression tests for stem symmetry between articulated (الـ) and bare forms.

The old stemmer was single-pass: it stripped one prefix, then if the remaining
word was still >=5 chars, stripped one suffix. This was asymmetric — articulated
forms cleared the gate and lost both prefix+suffix; bare forms with the same root
fell below the gate and only lost the prefix. Same root, different stem, no
substring overlap, broken multi-word matching.

The fix iterates prefix stripping so both forms converge. These tests lock that in.
"""
from hs_search_tool.search import _normalize_arabic_for_search, _stem_arabic_word


def test_articulated_and_bare_food_stem_to_same_root():
    """'أغذية' (bare) and 'الأغذية' (articulated) must produce the same stem."""
    bare = _normalize_arabic_for_search("أغذية")
    articulated = _normalize_arabic_for_search("الأغذية")
    assert bare == articulated, f"asymmetric stems: bare={bare!r}, articulated={articulated!r}"


def test_articulated_and_bare_devices_stem_to_same_root():
    """'أجهزة' (bare) and 'الأجهزة' (articulated) must produce the same stem."""
    bare = _normalize_arabic_for_search("أجهزة")
    articulated = _normalize_arabic_for_search("الأجهزة")
    assert bare == articulated, f"asymmetric stems: bare={bare!r}, articulated={articulated!r}"


def test_articulated_and_bare_batteries_stem_to_same_root():
    """'بطاريات' (bare plural) and 'البطاريات' (articulated plural) must align."""
    bare = _normalize_arabic_for_search("بطاريات")
    articulated = _normalize_arabic_for_search("البطاريات")
    assert bare == articulated, f"asymmetric stems: bare={bare!r}, articulated={articulated!r}"


def test_stem_does_not_over_strip_short_roots():
    """Words with very short trailing letters must not strip suffixes that would
    leave a root shorter than 3 chars."""
    # 'يد' (2 chars) — should pass through untouched
    assert _stem_arabic_word("يد") == "يد"
    # Single-character roots aren't stemmed (gate is len < 5 returns word unchanged)
    assert _stem_arabic_word("جهاز") == "جهاز"  # len 4, below the function's gate


def test_food_search_finds_articulated_data():
    """End-to-end: an engine search for 'food' (which synonym-maps to أغذية)
    must find rows whose AR name uses 'الأغذية' (the articulated form).
    This is the regression scenario that motivated the fix."""
    from hs_search_tool import SearchEngine
    from pathlib import Path
    engine = SearchEngine(data_dir=Path(__file__).parent.parent / "data")
    results = engine.search("food", limit=20)
    # At least one of the canonical "food machinery" codes should surface.
    hs_codes = {r.hs_code for r in results}
    expected_any = {"820830000000", "841981000002", "841981000003"}
    assert hs_codes & expected_any, (
        f"food search should find canonical food-machinery codes, "
        f"got {sorted(hs_codes)[:5]}"
    )
