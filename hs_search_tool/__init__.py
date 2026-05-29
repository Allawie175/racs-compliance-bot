"""
HS Search Tool — a deterministic search interface over SASO HS code data.

Designed as a drop-in backend for chatbots, REST APIs, or any orchestrator that
needs to answer compliance questions for Saudi Arabia imports.

Quick start:

    from hs_search_tool import SearchEngine
    engine = SearchEngine(data_dir="hs_search_tool/data")

    # Search
    for r in engine.search("جهاز كهربائي", limit=10):
        print(r.hs_code, r.product_name_ar, "->", r.certification.phrase_en)

    # Drill down
    detail = engine.get_details("903033000000")
    print(detail.regulation.name_en if detail.regulation else "Non-regulated")

See README.md for the full integration guide.
"""

from .models import (
    CertificationInfo,
    ChapterGroup,
    ParentCode,
    ProductDetail,
    RegulationInfo,
    SearchResult,
)
from .search import SearchEngine, SABER_DEEPLINK_TEMPLATE

__all__ = [
    "SearchEngine",
    "SearchResult",
    "ChapterGroup",
    "ProductDetail",
    "RegulationInfo",
    "ParentCode",
    "CertificationInfo",
    "SABER_DEEPLINK_TEMPLATE",
]

__version__ = "1.1.0"
