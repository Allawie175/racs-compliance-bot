"""
Local replacement for XDSQueryEngine, backed by hs_search_tool.SearchEngine.

Drop-in interface compatibility:
- search(query, page=1) returns the same dict shape XDS does, so the orchestrator
  can present options with HS code / product_name / regulation / certification_type.
- get_detail(url) accepts the URL string the orchestrator already passes, extracts
  the HS code from its `hscode=` query param (the same way the orchestrator's
  _extract_hs_code helper does), and returns a dict shaped like XDS's detail page.

This lets us flip between XDS and local by env var without touching the orchestrator.

Design notes:
- detail_url uses the format https://local.racs/hs?hscode=<HS_CODE>. The orchestrator's
  _extract_hs_code uses parse_qs(urlparse(url).query)["hscode"], which works unchanged.
- Pagination: XDS pages had ~10 results. We map page N to results [(N-1)*10 : N*10].
- We omit `regulation.estimated_cost` and `estimated_time_needed` from the chat-tier
  payload by design — those belong to the PDF tier per the migration response.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

# The bot runs from the repo root; data lives at hs_search_tool/data
_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "hs_search_tool" / "data"
DATA_DIR = Path(os.getenv("HS_SEARCH_DATA_DIR", _DEFAULT_DATA_DIR))

LOCAL_DETAIL_URL_TEMPLATE = "https://local.racs/hs?hscode={hs_code}"
SABER_PORTAL_URL = "https://saber.sa"

# Initialize once at module import. Loads ~1.4 MB into memory.
from hs_search_tool import SearchEngine

_engine = SearchEngine(data_dir=DATA_DIR)


class LocalXDSQueryEngine:
    """Drop-in replacement for tools.xds_query.XDSQueryEngine."""

    PAGE_SIZE = 10

    @classmethod
    def search(cls, query: str, page: int = 1) -> list[dict]:
        """Return XDS-shaped results for a search query (paginated)."""
        if not query or not query.strip():
            return []

        # Pull a generous slice once; slice client-side for pagination.
        all_results = _engine.search(query.strip(), limit=cls.PAGE_SIZE * 5)

        start = max(0, (page - 1) * cls.PAGE_SIZE)
        end = start + cls.PAGE_SIZE
        page_slice = all_results[start:end]

        out: list[dict] = []
        for r in page_slice:
            product_name = r.product_name_ar or r.product_name_en or ""
            regulation = r.regulation_name_en or r.regulation_name_ar or ""
            out.append({
                "hs_code": r.hs_code,
                "product_name": product_name,
                "parent_category": f"{r.chapter} — chapter prefix",
                "regulation": regulation,
                "certification_type": r.certification.phrase_en or r.certification.phrase_ar,
                "detail_url": LOCAL_DETAIL_URL_TEMPLATE.format(hs_code=r.hs_code),
            })
        return out

    @classmethod
    def get_detail(cls, url: str) -> Optional[dict]:
        """Resolve a detail URL to an XDS-shaped payload, omitting PDF-tier fields."""
        hs_code = cls._extract_hs_code(url)
        if not hs_code:
            return None

        detail = _engine.get_details(hs_code)
        if not detail:
            return None

        regulation_name = None
        regulation_summary = None
        regulation_pdf = None
        if detail.regulation:
            regulation_name = detail.regulation.name_en or detail.regulation.name_ar
            regulation_summary = detail.regulation.summary
            regulation_pdf = detail.regulation.pdf_link

        saber_links = {
            "hs_code_page": detail.saber_link,
            "saber_portal": SABER_PORTAL_URL,
        }
        if regulation_pdf:
            saber_links["regulation_pdf"] = regulation_pdf

        product_classification = (
            "Regulated — mandatory technical regulation"
            if detail.certification.is_regulated
            else "Non-Regulated — Free-Trade route"
        )

        # Structured requirements breakdown derived from req_code is the sole
        # source of truth for compliance requirements. The old certification_*
        # fields used to live here too and were derived from the legacy
        # certification_key bucket — they sometimes disagreed with the req_code
        # parse (e.g. listed "GCTS or Saber CoC" generically when req_code said
        # only QM is the option), which caused the model to render the wrong
        # alternatives. They're gone now; the model must use `requirements`.
        hs_row = _engine._hs_codes_by_code.get(detail.hs_code) or {}  # type: ignore[attr-defined]
        req_code = (hs_row.get("req_code") or "").strip()

        payload: dict = {
            "hs_code": detail.hs_code,
            "product_name_ar": detail.product_name_ar,
            "product_name_en": detail.product_name_en,
            "regulation_name": regulation_name,
            "regulation_summary": regulation_summary,
            "products_covered": detail.product_name_ar,
            "product_classification": product_classification,
            "saber_links": saber_links,
        }
        if req_code:
            payload["req_code"] = req_code
            payload["requirements"] = _engine.parse_req_code(req_code)  # type: ignore[attr-defined]

        # Parent context — helps Claude orient the user
        if detail.parent_4_description:
            payload["parent_4"] = {
                "code": detail.parent_4,
                "description": detail.parent_4_description,
            }
        if detail.parent_6_description:
            payload["parent_6"] = {
                "code": detail.parent_6,
                "description": detail.parent_6_description,
            }

        return payload

    @staticmethod
    def _extract_hs_code(url: str) -> Optional[str]:
        try:
            q = parse_qs(urlparse(url).query)
            code = q.get("hscode", [None])[0]
            return code if code else None
        except Exception:
            return None
