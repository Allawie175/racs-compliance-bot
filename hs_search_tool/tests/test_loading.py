"""Tests that the data tables load and the engine instantiates with expected state."""
from __future__ import annotations


def test_engine_loads(engine):
    assert engine is not None


def test_stats_within_expected_ranges(engine):
    stats = engine.stats()
    # We prepared from saber_master.csv which has ~5,221 HS codes
    assert 5000 <= stats["total_hs_codes"] <= 5500, stats
    # Most codes should match a regulation_id (>=90%). The remainder are
    # legitimately unmatched (placeholder '-' in source, or names not present
    # in regulations_metadata.csv).
    assert stats["with_regulation_id"] >= 0.90 * stats["total_hs_codes"], stats
    # 78 regulations from regulations_metadata.csv
    assert 60 <= stats["regulations_loaded"] <= 90, stats
    # Parent codes (4-digit + 6-digit unique prefixes)
    assert stats["parent_codes_loaded"] >= 2000, stats
    # Six standard certification phrases plus one fallback
    assert stats["certification_phrases"] >= 6, stats


def test_certification_distribution_makes_sense(engine):
    """Most HS codes should fall into 'saber_coc_or_qm'; some 'supplier_declaration_free_trade'."""
    stats = engine.stats()
    dist = stats["certification_distribution"]
    assert dist.get("saber_coc_or_qm", 0) > 1000, dist
    assert dist.get("supplier_declaration_free_trade", 0) > 100, dist
    # All keys must be known phrases
    known_keys = set(["supplier_declaration_free_trade", "saber_coc_or_qm",
                      "quality_mark_only", "gcts_or_qm", "multi_route",
                      "type_approval", "unknown"])
    assert set(dist.keys()).issubset(known_keys), set(dist.keys()) - known_keys
