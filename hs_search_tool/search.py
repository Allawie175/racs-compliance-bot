"""
HSSearchEngine — search interface over the prepared SASO data tables.

Public API (intended for use by chatbots, REST endpoints, or any orchestrator):

    from hs_search_tool import SearchEngine

    engine = SearchEngine(data_dir="hs_search_tool/data")

    # Keyword OR HS code search (auto-detects numeric vs text)
    results = engine.search("جهاز كهربائي", limit=10)

    # Group results by HS chapter for disambiguation menus
    groups = engine.search_grouped("battery")

    # Drill into a specific HS code
    detail = engine.get_details("903033000000")

    # Browse all codes under a prefix
    siblings = engine.get_by_prefix("8703", limit=25)

All public methods are deterministic — no AI calls, no live web requests.
Suitable as a backend for both chat tier and PDF report tier.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from .models import (
    CertificationInfo,
    ChapterGroup,
    ParentCode,
    ProductDetail,
    RegulationInfo,
    SearchResult,
)


# HS chapter labels (2-digit prefix -> Arabic / English short label).
# Authoritative WCO descriptions can be substituted later — for now we provide
# the most common ones our data uses so disambiguation menus read naturally.
CHAPTER_LABELS = {
    "25": ("معادن ومواد طبيعية", "Mineral products"),
    "32": ("دهانات وأصباغ", "Tanning, dyeing, paints"),
    "34": ("منظفات ومستحضرات", "Soaps, detergents, waxes"),
    "39": ("منتجات بلاستيكية", "Plastics and articles thereof"),
    "40": ("منتجات مطاطية", "Rubber and articles thereof"),
    "42": ("منتجات جلدية", "Articles of leather"),
    "44": ("خشب ومنتجاته", "Wood and articles of wood"),
    "48": ("ورق وكرتون", "Paper and paperboard"),
    "50": ("منسوجات حريرية", "Silk"),
    "52": ("قطن", "Cotton"),
    "54": ("ألياف صناعية", "Man-made filaments"),
    "55": ("ألياف صناعية متقطعة", "Man-made staple fibres"),
    "56": ("منسوجات غير منسوجة", "Nonwovens, twine, ropes"),
    "57": ("سجاد ومفروشات", "Carpets and floor coverings"),
    "61": ("ملابس محاكة", "Knitted apparel"),
    "62": ("ملابس غير محاكة", "Non-knitted apparel"),
    "63": ("منسوجات جاهزة", "Made-up textile articles"),
    "64": ("أحذية وملحقاتها", "Footwear and accessories"),
    "68": ("أحجار ومعادن", "Articles of stone, plaster, cement"),
    "69": ("سيراميك", "Ceramic products"),
    "70": ("زجاج ومنتجاته", "Glass and glassware"),
    "71": ("حلي ومجوهرات", "Jewellery, precious metals"),
    "72": ("حديد وصلب", "Iron and steel"),
    "73": ("منتجات الحديد والصلب", "Articles of iron or steel"),
    "74": ("نحاس", "Copper and articles thereof"),
    "76": ("ألمنيوم", "Aluminium and articles thereof"),
    "82": ("أدوات يدوية", "Tools, cutlery, spoons"),
    "83": ("منتجات معدنية متنوعة", "Miscellaneous articles of base metal"),
    "84": ("آلات ومعدات", "Machinery and mechanical appliances"),
    "85": ("أجهزة كهربائية", "Electrical machinery and equipment"),
    "87": ("مركبات وقطع غيار", "Vehicles and parts"),
    "90": ("أجهزة قياس وعلمية", "Optical, measuring, medical instruments"),
    "91": ("ساعات", "Clocks and watches"),
    "94": ("أثاث وإضاءة", "Furniture, lighting"),
    "95": ("ألعاب ومعدات رياضية", "Toys, games, sports equipment"),
    "96": ("منتجات صناعية متنوعة", "Miscellaneous manufactured articles"),
}


SABER_DEEPLINK_TEMPLATE = "https://saber.sa/Home/HSCodes?HSCodeCustoms={hs_code}"


def _is_numeric_query(q: str) -> bool:
    """Numeric queries should be HS code prefix searches, not keyword searches."""
    return bool(q) and all(c.isdigit() for c in q)


# Common Arabic suffixes stripped during stemming so plural/singular and
# feminine/masculine forms match each other (e.g. بطارية ↔ بطاريات).
# Order matters: longest first so "ات" is stripped before "ة".
_AR_SUFFIXES = ("ات", "ية", "ين", "ون", "ها", "ة", "ه", "ي", "ا")

# Common Arabic prefixes stripped from leading positions so query "جهاز" can
# match data "أجهزة" (broken plural with leading alef). Both ال (definite
# article) and broken-plural alef are common.
_AR_PREFIXES = ("ال", "ا")


def _stem_arabic_word(word: str) -> str:
    """Strip Arabic morphology iteratively so articulated and bare forms align.

    The previous single-pass stemmer was asymmetric: 'أغذية' (bare, 5 chars)
    stripped one leading alef and stopped at 'غذية' (4 chars, suffix-strip
    gated by len>=5). 'الأغذية' (articulated, 7 chars) stripped 'ال' down to
    5 chars and proceeded to strip the suffix, ending at 'اغذ' (3 chars).
    Different stems for the same root broke substring matching after synonym
    expansion.

    The iterative approach strips one prefix at a time until none apply, then
    one trailing suffix if length permits. Both 'أغذية' and 'الأغذية' now
    converge to 'غذية'. Conservative length gates (prefix-strip needs >=4
    remaining; suffix-strip needs >=3 remaining) keep over-stemming in check.
    """
    if len(word) < 5:
        return word
    # Iteratively strip one prefix at a time until none apply
    while len(word) >= 5:
        stripped = False
        for prefix in _AR_PREFIXES:
            if word.startswith(prefix) and len(word) - len(prefix) >= 4:
                word = word[len(prefix):]
                stripped = True
                break
        if not stripped:
            break
    # Then strip one trailing suffix (only if the word is still long enough)
    if len(word) >= 5:
        for suffix in _AR_SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                return word[:-len(suffix)]
    return word


def _normalize_arabic_for_search(text: str) -> str:
    """Light Arabic normalization + stemming for keyword matching.

    Strips diacritics/tatweel, unifies alef/yaa variants, then applies
    conservative stemming so query 'بطارية' matches data 'بطاريات' and
    'جهاز' matches data 'أجهزة'.
    """
    if not text:
        return ""
    s = str(text).strip().lower()
    s = s.replace("ـ", "")
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ى", "ي")
    # Don't fold ة -> ه here; stemming handles both forms.
    words = [_stem_arabic_word(w) for w in s.split() if w]
    return " ".join(words)


def _normalize_for_search(text: str) -> str:
    """Language-agnostic normalization. Detects Arabic vs Latin and applies
    appropriate stemming. Used for both data indexing and query parsing.
    """
    if not text:
        return ""
    s = str(text).strip()
    # If the string contains any Arabic letters, apply Arabic normalization;
    # else just lowercase for Latin script.
    if any("؀" <= c <= "ۿ" for c in s):
        return _normalize_arabic_for_search(s)
    return s.lower()


class SearchEngine:
    """In-memory search over the prepared SASO HS code tables.

    Loads ~5K HS codes, ~78 regulations, ~3K parent codes from CSV/JSON on
    instantiation. All queries run against the in-memory structures — no I/O
    during search calls. Suitable for long-running bot processes.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).resolve()
        if not self.data_dir.exists():
            raise FileNotFoundError(
                f"Data directory not found: {self.data_dir}. "
                "Run src/prepare_data.py first."
            )

        self._certification_phrases: dict[str, dict] = {}
        self._hs_codes: list[dict] = []
        self._hs_codes_by_code: dict[str, dict] = {}
        self._regulations: dict[str, dict] = {}
        self._parent_codes: dict[tuple[int, str], dict] = {}
        self._synonyms: dict[str, list[str]] = {}
        # req_code lookup table: cert_code -> {kind, name_en, name_ar, description_en}
        self._cert_codes: dict[str, dict] = {}
        # Precomputed for fast search (Arabic stemmed + English lowercased):
        self._normalized_product_name_ar: dict[str, str] = {}
        self._normalized_product_name_en: dict[str, str] = {}

        self._load()

    # ---------------- Loading ----------------

    def _load(self) -> None:
        self._load_certification_phrases()
        self._load_synonyms()
        self._load_requirements()
        self._load_parent_codes()
        self._load_hs_codes()

    def _load_requirements(self) -> None:
        """Load the unified requirements.csv (single source of truth for every
        component code: REG-XXX regulations and cert codes alike).

        Populates two internal indexes from the same source:
          - self._regulations[code]: legacy shape used by RegulationInfo builder
          - self._cert_codes[code]:  legacy shape used by parse_req_code()
        This lets the rest of the engine keep its existing call sites unchanged.
        """
        path = self.data_dir / "requirements.csv"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                code = (row.get("code") or "").strip()
                if not code:
                    continue
                kind = (row.get("kind") or "").strip()
                # Regulation rows feed the RegulationInfo lookup
                if kind == "regulation":
                    self._regulations[code] = {
                        "regulation_id": code,
                        "regulation_name_ar": (row.get("name_ar") or "").strip(),
                        "regulation_name_en": (row.get("name_en") or "").strip(),
                        "summary": (row.get("summary") or "").strip(),
                        "step_by_step_guide": (row.get("step_by_step_guide") or "").strip(),
                        "estimated_cost": (row.get("estimated_cost") or "").strip(),
                        "estimated_time_needed": (row.get("estimated_time") or "").strip(),
                        "pdf_link": (row.get("pdf_link") or "").strip(),
                        "required_documents": (row.get("required_documents") or "").strip(),
                        "issuing_authorities": (row.get("issuing_authorities") or "").strip(),
                        "notes": (row.get("notes") or "").strip(),
                        "slug": code.lower().replace("_", "-"),
                    }
                # Every code (including regulations) feeds the cert-code lookup
                # so parse_req_code() can classify any segment it sees.
                self._cert_codes[code] = {
                    "code": code,
                    "kind": kind or "unknown",
                    "name_en": (row.get("name_en") or "").strip(),
                    "name_ar": (row.get("name_ar") or "").strip(),
                    "description_en": (row.get("summary") or "").strip(),
                    "pdf_link": (row.get("pdf_link") or "").strip(),
                    "estimated_cost": (row.get("estimated_cost") or "").strip(),
                    "estimated_cost_ar": (row.get("estimated_cost_ar") or "").strip(),
                    "estimated_time": (row.get("estimated_time") or "").strip(),
                    "estimated_time_ar": (row.get("estimated_time_ar") or "").strip(),
                    "required_documents": (row.get("required_documents") or "").strip(),
                    "required_documents_ar": (row.get("required_documents_ar") or "").strip(),
                    "step_by_step_guide": (row.get("step_by_step_guide") or "").strip(),
                    "step_by_step_guide_ar": (row.get("step_by_step_guide_ar") or "").strip(),
                    "issuing_authorities": (row.get("issuing_authorities") or "").strip(),
                    "issuing_authorities_ar": (row.get("issuing_authorities_ar") or "").strip(),
                    "notes": (row.get("notes") or "").strip(),
                    "notes_ar": (row.get("notes_ar") or "").strip(),
                }

    def parse_req_code(self, req_code: str) -> dict:
        """Parse `REG-XXX|cert(-cert)*|extra*` into a structured breakdown.

        Returns:
            {
                "raw": "REG-056|QM-COC|WEC",
                "regulation_id": "REG-056",
                "cert_options": [{code, name_en, name_ar, ...}, ...],  # pick ONE
                "extras":       [{code, name_en, name_ar, ...}, ...],  # ALL required
            }
        """
        empty = {"raw": req_code or "", "regulation_id": None, "cert_options": [], "extras": []}
        if not req_code:
            return empty
        segments = [s.strip() for s in req_code.split("|") if s.strip()]
        if not segments:
            return empty

        regulation_id = segments[0]
        cert_options: list[dict] = []
        extras: list[dict] = []

        for seg in segments[1:]:
            # Inside a segment, `-` separates OR-alternates (e.g. QM-COC).
            # Compound cert names are already underscored (e.g. SELF_DEC), so `-`
            # is unambiguously the OR operator here.
            sub_codes = [c.strip() for c in seg.split("-") if c.strip()]
            if not sub_codes:
                continue
            # If any sub-code is an "extra" kind, treat the whole segment as extras
            # individually. If all are "cert_option" (or unknown), treat the segment
            # as one OR-group.
            kinds = [(self._cert_codes.get(c) or {}).get("kind") for c in sub_codes]
            if all(k == "extra" for k in kinds):
                for c in sub_codes:
                    rec = self._cert_code_record(c)
                    rec["kind"] = "extra"
                    extras.append(rec)
            else:
                # Mixed or all-options: surface as an OR-group of cert options.
                # Force kind="cert_option" so the inline tag matches array
                # placement — without this, a code whose default kind in
                # requirements.csv is "extra" (e.g. IECEE) appears inside
                # cert_options carrying kind="extra", and the model reads
                # that tag and renders it as an additional requirement
                # instead of an alternative.
                for c in sub_codes:
                    rec = self._cert_code_record(c)
                    rec["kind"] = "cert_option"
                    cert_options.append(rec)

        return {
            "raw": req_code,
            "regulation_id": regulation_id,
            "cert_options": cert_options,
            "extras": extras,
        }

    def _cert_code_record(self, code: str) -> dict:
        """Resolve a cert code to a record that includes name, description, and
        procedural fields (bilingual). Procedural fields are mostly populated
        for the SABER cert codes; regulations have richer data in `summary`
        and most procedural fields empty until RACS fills them.
        """
        meta = self._cert_codes.get(code)
        if meta:
            return {
                "code": code,
                "kind": meta.get("kind", ""),
                "name_en": meta.get("name_en", ""),
                "name_ar": meta.get("name_ar", ""),
                "description_en": meta.get("description_en", ""),
                "required_documents": meta.get("required_documents", ""),
                "required_documents_ar": meta.get("required_documents_ar", ""),
                "estimated_cost": meta.get("estimated_cost", ""),
                "estimated_cost_ar": meta.get("estimated_cost_ar", ""),
                "estimated_time": meta.get("estimated_time", ""),
                "estimated_time_ar": meta.get("estimated_time_ar", ""),
                "step_by_step_guide": meta.get("step_by_step_guide", ""),
                "step_by_step_guide_ar": meta.get("step_by_step_guide_ar", ""),
                "issuing_authorities": meta.get("issuing_authorities", ""),
                "issuing_authorities_ar": meta.get("issuing_authorities_ar", ""),
                "notes": meta.get("notes", ""),
                "notes_ar": meta.get("notes_ar", ""),
            }
        return {"code": code, "kind": "unknown", "name_en": code, "name_ar": code, "description_en": ""}

    def _load_certification_phrases(self) -> None:
        path = self.data_dir / "certification_phrases.json"
        with open(path, "r", encoding="utf-8") as f:
            self._certification_phrases = json.load(f)

    def _load_synonyms(self) -> None:
        """Load optional bilingual synonyms map. Missing file is fine."""
        path = self.data_dir / "synonyms.json"
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # Format: { "canonical_term": ["synonym1", "synonym2", ...], ... }
            # Keys starting with "_" are treated as metadata and skipped.
            for canonical, syns in (raw or {}).items():
                if canonical.startswith("_"):
                    continue
                if not canonical or not isinstance(syns, list):
                    continue
                # Normalize all keys + values to the same form used in search
                key = _normalize_for_search(canonical)
                vals = [_normalize_for_search(s) for s in syns if s]
                vals = [v for v in vals if v]
                if key and vals:
                    self._synonyms[key] = vals
        except (json.JSONDecodeError, OSError):
            # Bad file shouldn't crash the engine
            pass

    def _load_parent_codes(self) -> None:
        path = self.data_dir / "parent_codes.csv"
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                level = int(row["level"])
                code = row["code"].strip()
                self._parent_codes[(level, code)] = row

    def _load_hs_codes(self) -> None:
        path = self.data_dir / "hs_codes.csv"
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = (row.get("hs_code") or "").strip()
                if not code:
                    continue
                self._hs_codes.append(row)
                self._hs_codes_by_code[code] = row
                self._normalized_product_name_ar[code] = _normalize_arabic_for_search(
                    row.get("product_name_ar", "")
                )
                # English name: simple lowercase normalization (no stemming for now)
                self._normalized_product_name_en[code] = (
                    row.get("product_name_en", "") or ""
                ).strip().lower()

    # ---------------- Build helpers ----------------

    def _build_certification_info(self, key: str) -> CertificationInfo:
        meta = self._certification_phrases.get(key) or self._certification_phrases.get("unknown") or {}
        return CertificationInfo(
            key=key,
            phrase_en=meta.get("en", ""),
            phrase_ar=meta.get("ar", ""),
            is_regulated=bool(meta.get("regulated", True)),
        )

    def _build_search_result(self, row: dict) -> SearchResult:
        cert_key = (row.get("certification_key") or "unknown").strip()
        regulation_id = (row.get("regulation_id") or "").strip() or None
        regulation_name_ar = (row.get("regulation_name_ar") or "").strip() or None
        regulation_name_en = None
        if regulation_id and regulation_id in self._regulations:
            en = (self._regulations[regulation_id].get("regulation_name_en") or "").strip()
            regulation_name_en = en or None
        return SearchResult(
            hs_code=row["hs_code"],
            product_name_ar=(row.get("product_name_ar") or "").strip(),
            product_name_en=(row.get("product_name_en") or "").strip() or None,
            chapter=(row.get("chapter") or "").strip(),
            parent_4=(row.get("parent_4") or "").strip(),
            parent_6=(row.get("parent_6") or "").strip(),
            regulation_id=regulation_id,
            regulation_name_ar=regulation_name_ar,
            regulation_name_en=regulation_name_en,
            certification=self._build_certification_info(cert_key),
        )

    def _build_regulation_info(self, regulation_id: str) -> Optional[RegulationInfo]:
        row = self._regulations.get(regulation_id)
        if not row:
            return None
        cs = row.get("confidence_score")
        try:
            cs_float = float(cs) if cs else None
        except (TypeError, ValueError):
            cs_float = None
        return RegulationInfo(
            regulation_id=regulation_id,
            slug=(row.get("slug") or regulation_id.lower()).strip(),
            name_ar=(row.get("regulation_name_ar") or "").strip() or None,
            name_en=(row.get("regulation_name_en") or "").strip() or None,
            summary=(row.get("summary") or "").strip() or None,
            step_by_step_guide=(row.get("step_by_step_guide") or "").strip() or None,
            estimated_cost=(row.get("estimated_cost") or "").strip() or None,
            estimated_time_needed=(row.get("estimated_time_needed") or "").strip() or None,
            confidence_score=cs_float,
            pdf_link=(row.get("pdf_link") or "").strip() or None,
        )

    # ---------------- Public API ----------------

    def _expand_query_tokens(self, query: str) -> list[str]:
        """Tokenize + normalize + apply synonyms.

        Returns a flat list of tokens (no OR-groups). When a token matches a
        canonical entry in the synonyms map, the canonical form replaces it.
        This is the simplest expansion that broadens recall without explosion.
        """
        raw_tokens = [t for t in re.split(r"\s+", query) if t.strip()]
        out: list[str] = []
        for tok in raw_tokens:
            norm = _normalize_for_search(tok)
            if not norm:
                continue
            # If user wrote a synonym, replace with the canonical form's tokens
            for canonical, syns in self._synonyms.items():
                if norm == canonical or norm in syns:
                    norm = canonical
                    break
            out.append(norm)
        return out

    def _row_matches_all_tokens(self, hs_code: str, tokens: list[str]) -> bool:
        """A row matches if every token is a substring of either AR or EN name."""
        name_ar = self._normalized_product_name_ar.get(hs_code, "")
        name_en = self._normalized_product_name_en.get(hs_code, "")
        for tok in tokens:
            if tok in name_ar or tok in name_en:
                continue
            return False
        return True

    def _token_match_count(self, hs_code: str, tokens: list[str]) -> int:
        """Count how many tokens appear (as substrings) in either AR or EN name."""
        name_ar = self._normalized_product_name_ar.get(hs_code, "")
        name_en = self._normalized_product_name_en.get(hs_code, "")
        return sum(1 for t in tokens if (t in name_ar or t in name_en))

    def _ranked_keyword_rows(self, tokens: list[str]) -> list[dict]:
        """Return rows matching at least one token, ranked by match-count desc, then HS code asc.

        This gives precision-when-possible (rows that match every token come first)
        and falls back to recall-when-needed (rows matching some tokens still surface).
        Matches XDS's effective OR-tokenization while still preferring high-precision hits.
        """
        scored: list[tuple[int, str, dict]] = []
        for r in self._hs_codes:
            count = self._token_match_count(r["hs_code"], tokens)
            if count > 0:
                scored.append((count, r["hs_code"], r))
        # Sort: most matched tokens first, then HS code ascending for stability
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [r for _, _, r in scored]

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search by HS code (numeric prefix) or keyword (substring).

        Numeric: prefix match. "8703" -> all HS codes starting with 8703.
        Keyword: substring match in normalized Arabic and English product names.
                 Multi-word queries are tokenized; results are ranked by how many
                 tokens they match (descending). Rows matching every token come
                 first; rows matching some tokens still surface as fallback recall.
                 Synonyms in data/synonyms.json are expanded automatically.

        Returns up to `limit` results.
        """
        query = (query or "").strip()
        if not query:
            return []

        if _is_numeric_query(query):
            rows = [r for r in self._hs_codes if r["hs_code"].startswith(query)]
            rows.sort(key=lambda r: r["hs_code"])
        else:
            tokens = self._expand_query_tokens(query)
            if not tokens:
                return []
            rows = self._ranked_keyword_rows(tokens)

        rows = rows[:limit]
        return [self._build_search_result(r) for r in rows]

    def search_grouped(self, query: str, per_chapter_limit: int = 5) -> list[ChapterGroup]:
        """Same as search() but groups results by 2-digit HS chapter.

        Useful for disambiguation menus — when a vague keyword spans many
        chapters, the chat can offer the user a chapter to drill into first.
        """
        query = (query or "").strip()
        if not query:
            return []

        if _is_numeric_query(query):
            matching_rows = [r for r in self._hs_codes if r["hs_code"].startswith(query)]
        else:
            tokens = self._expand_query_tokens(query)
            if not tokens:
                return []
            matching_rows = self._ranked_keyword_rows(tokens)

        by_chapter: dict[str, list[dict]] = defaultdict(list)
        for r in matching_rows:
            by_chapter[r["chapter"]].append(r)

        groups: list[ChapterGroup] = []
        for chapter, rows in sorted(by_chapter.items()):
            rows.sort(key=lambda r: r["hs_code"])
            labels = CHAPTER_LABELS.get(chapter)
            label = f"{labels[0]} ({labels[1]})" if labels else f"Chapter {chapter}"
            groups.append(ChapterGroup(
                chapter=chapter,
                chapter_label=label,
                count=len(rows),
                results=[self._build_search_result(r) for r in rows[:per_chapter_limit]],
            ))
        groups.sort(key=lambda g: g.count, reverse=True)
        return groups

    def get_by_prefix(self, prefix: str, limit: int = 25) -> list[SearchResult]:
        """Return all HS codes starting with `prefix` (2 / 4 / 6 / 8 / 10 / 12 digits)."""
        prefix = (prefix or "").strip()
        if not prefix or not prefix.isdigit():
            return []
        rows = [r for r in self._hs_codes if r["hs_code"].startswith(prefix)]
        rows.sort(key=lambda r: r["hs_code"])
        return [self._build_search_result(r) for r in rows[:limit]]

    def get_details(self, hs_code: str) -> Optional[ProductDetail]:
        """Return full detail for a single HS code, or None if not found."""
        hs_code = (hs_code or "").strip()
        if not hs_code:
            return None
        row = self._hs_codes_by_code.get(hs_code)
        if not row:
            return None
        cert_key = (row.get("certification_key") or "unknown").strip()
        certification = self._build_certification_info(cert_key)
        regulation_id = (row.get("regulation_id") or "").strip() or None
        regulation = self._build_regulation_info(regulation_id) if regulation_id else None

        p4 = (row.get("parent_4") or "").strip()
        p6 = (row.get("parent_6") or "").strip()
        p4_desc = self._parent_description(4, p4)
        p6_desc = self._parent_description(6, p6)

        return ProductDetail(
            hs_code=hs_code,
            product_name_ar=(row.get("product_name_ar") or "").strip(),
            product_name_en=(row.get("product_name_en") or "").strip() or None,
            chapter=(row.get("chapter") or "").strip(),
            parent_4=p4,
            parent_4_description=p4_desc,
            parent_6=p6,
            parent_6_description=p6_desc,
            regulation=regulation,
            certification=certification,
            saber_link=SABER_DEEPLINK_TEMPLATE.format(hs_code=hs_code),
            standards_available=regulation is not None,  # placeholder: true if we have regulation data
            pdf_report_available=regulation is not None,
        )

    def get_parent(self, code: str, level: int) -> Optional[ParentCode]:
        """Return parent code metadata for a 4-digit or 6-digit prefix."""
        row = self._parent_codes.get((level, code.strip()))
        if not row:
            return None
        reg_ids = [r for r in (row.get("regulation_ids") or "").split("|") if r]
        return ParentCode(
            code=row["code"],
            level=int(row["level"]),
            description_ar_derived=(row.get("description_ar_derived") or "").strip(),
            child_count=int(row.get("child_count", 0)),
            regulation_ids=reg_ids,
        )

    def chapter_label(self, chapter: str) -> Optional[str]:
        """Return the bilingual chapter label, if known."""
        labels = CHAPTER_LABELS.get(chapter.strip())
        if not labels:
            return None
        return f"{labels[0]} ({labels[1]})"

    # ---------------- Stats / introspection ----------------

    def stats(self) -> dict:
        """Quick health-check summary. Useful for tests and ops dashboards."""
        cert_counts: dict[str, int] = defaultdict(int)
        regulated = 0
        with_regulation = 0
        for r in self._hs_codes:
            k = r.get("certification_key") or "unknown"
            cert_counts[k] += 1
            if r.get("regulation_id"):
                with_regulation += 1
            phrase = self._certification_phrases.get(k) or {}
            if phrase.get("regulated"):
                regulated += 1
        return {
            "total_hs_codes": len(self._hs_codes),
            "with_regulation_id": with_regulation,
            "regulated_codes": regulated,
            "regulations_loaded": len(self._regulations),
            "parent_codes_loaded": len(self._parent_codes),
            "certification_phrases": len(self._certification_phrases),
            "certification_distribution": dict(cert_counts),
        }

    # ---------------- Internal helpers ----------------

    def _parent_description(self, level: int, code: str) -> Optional[str]:
        if not code:
            return None
        row = self._parent_codes.get((level, code))
        if not row:
            return None
        desc = (row.get("description_ar_derived") or "").strip()
        return desc or None
