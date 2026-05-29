"""Data models for HS search tool results."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class CertificationInfo:
    """Standard certification phrase + language variants."""
    key: str
    phrase_en: str
    phrase_ar: str
    is_regulated: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchResult:
    """One row in a search result list. Lightweight — used for chat tier responses."""
    hs_code: str
    product_name_ar: str
    product_name_en: Optional[str]
    chapter: str
    parent_4: str
    parent_6: str
    regulation_id: Optional[str]
    regulation_name_ar: Optional[str]
    regulation_name_en: Optional[str]
    certification: CertificationInfo

    def to_dict(self) -> dict:
        data = asdict(self)
        # Flatten certification for easier JSON consumption
        data["certification"] = self.certification.to_dict()
        return data


@dataclass
class ChapterGroup:
    """Disambiguation grouping — for vague queries that span multiple HS chapters."""
    chapter: str
    chapter_label: str
    count: int
    results: list[SearchResult] = field(default_factory=list)


@dataclass
class ParentCode:
    """A 4-digit or 6-digit parent code with derived description."""
    code: str
    level: int
    description_ar_derived: str
    child_count: int
    regulation_ids: list[str]


@dataclass
class RegulationInfo:
    """Full regulation metadata — used in detail pages and as PDF generation input."""
    regulation_id: str
    slug: str
    name_ar: Optional[str]
    name_en: Optional[str]
    summary: Optional[str]
    step_by_step_guide: Optional[str]
    estimated_cost: Optional[str]
    estimated_time_needed: Optional[str]
    confidence_score: Optional[float]
    pdf_link: Optional[str]


@dataclass
class ProductDetail:
    """Full per-HS-code detail. Returned when user drills down to a single code.

    Includes everything in SearchResult plus parent descriptions, regulation
    metadata, the SABER deep-link, and a hook flag for the PDF tier.
    """
    hs_code: str
    product_name_ar: str
    product_name_en: Optional[str]
    chapter: str
    parent_4: str
    parent_4_description: Optional[str]
    parent_6: str
    parent_6_description: Optional[str]
    regulation: Optional[RegulationInfo]
    certification: CertificationInfo
    saber_link: str
    standards_available: bool  # True if hs_codes_standards_lookup.csv has entries for this code
    pdf_report_available: bool  # True if a deep PDF can be generated for this code

    def to_dict(self) -> dict:
        data = asdict(self)
        data["certification"] = self.certification.to_dict()
        if self.regulation:
            data["regulation"] = asdict(self.regulation)
        return data
