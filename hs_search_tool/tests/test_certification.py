"""Tests verifying the 4 standard certification phrases match XDS's vocabulary."""
from __future__ import annotations


def test_phrase_supplier_declaration_matches_xds(engine):
    info = engine._build_certification_info("supplier_declaration_free_trade")
    assert info.phrase_en == "Requires Supplier Conformity Declaration (Free-Trade)"
    assert info.is_regulated is False


def test_phrase_saber_coc_or_qm_matches_xds(engine):
    info = engine._build_certification_info("saber_coc_or_qm")
    assert info.phrase_en == "Requires Saber Certificate of Conformity or Quality Mark Certificate"
    assert info.is_regulated is True


def test_phrase_gcts_or_qm_matches_xds(engine):
    info = engine._build_certification_info("gcts_or_qm")
    assert info.phrase_en == "Requires GCTS Certificate or Quality Mark Certificate"
    assert info.is_regulated is True


def test_phrase_multi_route_matches_xds(engine):
    info = engine._build_certification_info("multi_route")
    assert "Saber Certificate of Conformity" in info.phrase_en
    assert "GCTS Certificate" in info.phrase_en
    assert "IECEE Certificate" in info.phrase_en
    assert "Quality Mark Certificate" in info.phrase_en
    assert info.is_regulated is True


def test_phrase_unknown_key_falls_back_to_unknown(engine):
    """A nonsense key should not crash — falls back to 'unknown' phrase."""
    info = engine._build_certification_info("totally_made_up_key")
    assert info.phrase_en  # non-empty
    assert info.phrase_ar  # non-empty


def test_all_phrases_have_bilingual_text(engine):
    """Every defined phrase must have both English and Arabic text."""
    for key, meta in engine._certification_phrases.items():
        assert meta.get("en"), f"phrase {key} missing English"
        assert meta.get("ar"), f"phrase {key} missing Arabic"
        assert "regulated" in meta, f"phrase {key} missing regulated flag"
