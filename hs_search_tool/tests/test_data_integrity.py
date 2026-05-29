"""Tests for the data-integrity fixes around the placeholder-regulation bug."""
from __future__ import annotations


def test_placeholder_regulation_not_matched_to_real_one(engine):
    """The 'tin ore' code 260900000002 had reg='-' in source and must NOT be
    fuzzy-mapped to a real regulation."""
    detail = engine.get_details("260900000002")
    assert detail is not None, "expected the tin-ore code to be present"
    # Source data has Technical Regulation = '-' (placeholder) so we must NOT
    # have a regulation_id.
    assert detail.regulation is None, (
        f"placeholder '-' regulation was wrongly matched to "
        f"{detail.regulation.regulation_id if detail.regulation else None}"
    )
    # Cert key derived from Scraped_From=NonReg must be the free-trade phrase
    assert detail.certification.key == "supplier_declaration_free_trade"
    assert detail.certification.is_regulated is False


def test_all_nonreg_codes_have_no_regulation_id(engine):
    """Every code whose certification_key is 'supplier_declaration_free_trade'
    should NOT carry a regulation_id (those source rows had reg='-' )."""
    bad = []
    for row in engine._hs_codes:
        if row.get("certification_key") == "supplier_declaration_free_trade":
            if (row.get("regulation_id") or "").strip():
                bad.append(row["hs_code"])
    assert not bad, f"found {len(bad)} free-trade codes wrongly carrying a regulation_id: {bad[:5]}"


def test_no_regulation_id_yields_certification_still_set(engine):
    """A code without a regulation_id must still have a certification phrase."""
    for row in engine._hs_codes:
        if not (row.get("regulation_id") or "").strip():
            detail = engine.get_details(row["hs_code"])
            assert detail.certification is not None
            assert detail.certification.phrase_en  # non-empty
            return
    raise AssertionError("no rows without regulation_id found — unexpected")
