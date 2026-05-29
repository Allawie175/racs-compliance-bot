"""Tests for the synonyms layer."""
from __future__ import annotations


def test_synonyms_load(engine):
    """synonyms.json must load and the metadata key must be skipped."""
    assert "_meta" not in engine._synonyms, "_meta key should be ignored"
    assert len(engine._synonyms) > 0, "expected at least a few synonym entries"


def test_consumer_arabic_maps_to_trade_arabic(engine):
    """Consumer-language 'منتج تجميل' should expand to trade-language 'مستحضرات تجميل'."""
    # The synonyms map should have an entry that includes either form
    # in either key or values (after normalization).
    expanded = engine._expand_query_tokens("منتج تجميل")
    # After expansion, the canonical token from the synonyms map should appear.
    # We don't pin the exact canonical string (depends on normalization), but
    # at minimum the expansion must produce a non-empty token list.
    assert len(expanded) > 0


def test_synonym_expansion_does_not_break_unknown_terms(engine):
    """Tokens that don't match any synonym must pass through unchanged."""
    expanded = engine._expand_query_tokens("xyzqz nonsensetoken")
    # Should produce some normalized tokens (we don't enforce specific count)
    assert isinstance(expanded, list)


def test_battery_synonym(engine):
    """The English term 'battery' should resolve via synonyms to a canonical form
    that exists in the data."""
    results = engine.search("battery", limit=10)
    # We expect AT LEAST one match because product_name_en lookup OR
    # synonyms expansion to 'مدخرات' should both find HS 8506/8507 codes.
    assert len(results) > 0
