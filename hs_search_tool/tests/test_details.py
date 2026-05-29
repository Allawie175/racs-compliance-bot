"""Tests for get_details() — the drill-down detail page."""
from __future__ import annotations


def _pick_known_code(engine, prefix="85"):
    sample = engine.search(prefix, limit=1)
    assert sample, f"no rows found for prefix {prefix}"
    return sample[0].hs_code


def test_get_details_for_unknown_code_returns_none(engine):
    assert engine.get_details("00000000000000") is None
    assert engine.get_details("") is None
    assert engine.get_details(None) is None


def test_get_details_returns_full_detail(engine):
    code = _pick_known_code(engine)
    detail = engine.get_details(code)
    assert detail is not None
    assert detail.hs_code == code
    assert detail.chapter == code[:2]
    assert detail.parent_4 == code[:4]
    assert detail.parent_6 == code[:6]
    assert detail.product_name_ar  # non-empty
    assert detail.certification is not None
    assert detail.saber_link.endswith(code)


def test_get_details_saber_link_format(engine):
    code = _pick_known_code(engine)
    detail = engine.get_details(code)
    assert detail.saber_link == f"https://saber.sa/Home/HSCodes?HSCodeCustoms={code}"


def test_get_details_regulation_info_loaded_when_available(engine):
    """For most codes, the regulation FK should be populated and the regulation lookupable."""
    code = _pick_known_code(engine)
    detail = engine.get_details(code)
    if detail.regulation is not None:
        assert detail.regulation.regulation_id
        assert detail.regulation.slug
        # Should have at least one of name_ar or name_en
        assert detail.regulation.name_ar or detail.regulation.name_en


def test_get_details_parent_descriptions_when_derivable(engine):
    """Parent 4 and 6 descriptions are derived from siblings; may be empty for rare codes."""
    code = _pick_known_code(engine)
    detail = engine.get_details(code)
    # Type contract: strings or None
    assert detail.parent_4_description is None or isinstance(detail.parent_4_description, str)
    assert detail.parent_6_description is None or isinstance(detail.parent_6_description, str)


def test_get_details_to_dict_serializable(engine):
    """The detail must serialize cleanly to a dict (for JSON responses)."""
    import json
    code = _pick_known_code(engine)
    detail = engine.get_details(code)
    d = detail.to_dict()
    # All values must be JSON-serializable
    json.dumps(d, ensure_ascii=False, default=str)
    # Required fields present
    for key in ("hs_code", "product_name_ar", "chapter", "parent_4", "parent_6",
                "certification", "saber_link", "standards_available",
                "pdf_report_available"):
        assert key in d, f"missing {key}"


def test_non_regulated_code_has_correct_phrase(engine):
    """Find a non-regulated code and verify its certification key + phrase."""
    # Use one of the codes we know is non-regulated from data inspection
    detail = engine.get_details("250100100009")
    if detail is None:
        # If specific code not in data, find any non-regulated code
        for r in engine._hs_codes:
            if r.get("certification_key") == "supplier_declaration_free_trade":
                detail = engine.get_details(r["hs_code"])
                break
    assert detail is not None
    assert detail.certification.key == "supplier_declaration_free_trade"
    assert detail.certification.is_regulated is False
    assert "Free-Trade" in detail.certification.phrase_en
    assert "حره" in detail.certification.phrase_ar or "حرة" in detail.certification.phrase_ar


def test_regulated_code_has_regulated_flag(engine):
    """A standard SABER-regulated code must have is_regulated=True."""
    for r in engine._hs_codes:
        if r.get("certification_key") == "saber_coc_or_qm":
            detail = engine.get_details(r["hs_code"])
            assert detail is not None
            assert detail.certification.is_regulated is True
            assert "Saber" in detail.certification.phrase_en or "SABER" in detail.certification.phrase_en
            return
    raise AssertionError("no saber_coc_or_qm code found in data")
