# RACs HS Code Search Tool

A self-contained, deterministic HS-code lookup engine for Saudi Arabia compliance, built directly from SASO data. No external service calls, no AI inference inside the search itself — the orchestrating chatbot can use Claude (or any LLM) to wrap these results in natural language.

**Designed to be dropped into any Python project** (Telegram bot, REST API, CLI, n8n custom node) as a single package directory.

---

## Why this exists

Earlier versions of the RACs bot were proxied through XDS Solutions' public website. That approach was fragile (HTML scraping broke), shallow (XDS shows generic boilerplate), and incomplete (XDS covers 27 regulations; SASO has 68). This package replaces that XDS dependency with a local search engine over our own master data, giving deeper answers with no network risk.

The XDS deep-dive that informed this design lives at the repo root in `XDS_DEEP_DIVE.md`.

---

## What's in here

```
hs_search_tool/
├── README.md                   ← this file
├── INTEGRATION_GUIDE.md        ← how to plug into a bot / API / agent
├── requirements.txt
├── __init__.py                 ← package entry: exports SearchEngine, models
├── search.py                   ← SearchEngine class — public API
├── models.py                   ← SearchResult, ProductDetail, etc.
├── prepare_data.py             ← rebuilds the data tables from SASO masters
├── data/                       ← pre-built data the engine loads on import
│   ├── hs_codes.csv            (5,221 HS codes with regulation FK)
│   ├── regulations.csv         (78 regulations with bilingual names + metadata)
│   ├── parent_codes.csv        (3,093 4/6-digit prefixes with derived descriptions)
│   └── certification_phrases.json  (7 standard certification phrases EN+AR)
├── tests/                      ← pytest suite (42 tests, all passing)
│   ├── conftest.py
│   ├── test_loading.py
│   ├── test_search.py
│   ├── test_disambiguation.py
│   ├── test_details.py
│   ├── test_certification.py
│   └── test_chapter_label.py
├── examples/
│   └── demo.py                 ← reproduces the Waleed conversation flow
└── handover/
    └── DEMO_OUTPUT.txt         ← captured demo output for verification
```

---

## Quick start

```python
from hs_search_tool import SearchEngine

engine = SearchEngine(data_dir="hs_search_tool/data")

# Keyword search (Arabic or English)
for r in engine.search("بطارية", limit=5):
    print(r.hs_code, "—", r.product_name_ar)
    print("  Certification:", r.certification.phrase_en)

# Tree-grouped disambiguation (for vague queries)
for g in engine.search_grouped("بطارية"):
    print(f"Chapter {g.chapter} ({g.chapter_label}): {g.count} results")

# HS code prefix search
for r in engine.search("8703", limit=10):
    print(r.hs_code, "—", r.product_name_ar)

# Drill into a specific code
detail = engine.get_details("903040000001")
print(detail.regulation.name_en)
print(detail.certification.phrase_ar)
print(detail.saber_link)
```

See **INTEGRATION_GUIDE.md** for a full Telegram-bot example.

---

## Run the tests

```bash
py -3 -m pytest hs_search_tool/tests/ -v
```

Expected: **42 passed**.

## Run the demo

```bash
py -3 hs_search_tool/examples/demo.py
```

Output is captured in `handover/DEMO_OUTPUT.txt` for reference.

---

## Data tables (what's inside)

### `data/hs_codes.csv` (5,221 rows)

| Column | Meaning |
|--------|---------|
| `hs_code` | 12-digit HS code (string) |
| `chapter` | 2-digit chapter prefix |
| `parent_4` | 4-digit heading prefix |
| `parent_6` | 6-digit subheading prefix |
| `product_name_ar` | Product description (Arabic) |
| `regulation_id` | FK to `regulations.csv` (e.g. `REG-030`); may be empty |
| `regulation_name_ar` | Original Arabic regulation name from saber_master |
| `certification_key` | One of: `saber_coc_or_qm`, `supplier_declaration_free_trade`, `gcts_or_qm`, `multi_route`, `quality_mark_only`, `type_approval`, `unknown` |
| `scraped_from` | Original source channel from saber_master (audit trail) |

Coverage: 5,098 / 5,221 codes (97.6%) match to a regulation_id. The remaining 123 use regulation names not present in `regulations_metadata.csv`.

### `data/regulations.csv` (78 rows)

| Column | Meaning |
|--------|---------|
| `regulation_id` | `REG-XXX` identifier (PK) |
| `slug` | URL-safe slug |
| `regulation_name_ar` | Arabic name |
| `regulation_name_en` | English name (when available — 55 of 78 have it) |
| `summary` | Plain-language overview |
| `step_by_step_guide` | Compliance steps (markdown) |
| `estimated_cost` | Cost range (text) |
| `estimated_time_needed` | Timeline estimate (text) |
| `confidence_score` | 0.0–1.0 |
| `pdf_link` | Path to source PDF |

These additional fields (`step_by_step_guide`, `estimated_cost`, `estimated_time_needed`) are the hook for the **PDF report tier** — they're available in the data but the chat tier should mention them as "available in the full PDF report" rather than dumping them inline.

### `data/parent_codes.csv` (3,093 rows)

| Column | Meaning |
|--------|---------|
| `code` | 4 or 6-digit prefix |
| `level` | 4 or 6 |
| `description_ar_derived` | **Derived** from most common child product name (NOT authoritative WCO description) |
| `child_count` | Number of 12-digit codes with this prefix |
| `regulation_ids` | Pipe-separated list of regulations covering codes under this prefix |

> **Known limitation**: `description_ar_derived` is generated from sibling codes. For some prefixes it picks an unrepresentative example. Future improvement: source authoritative WCO HS nomenclature CSV and merge in `description_ar_authoritative` and `description_en_authoritative` columns.

### `data/certification_phrases.json`

The 7 standard certification phrases (4 from XDS + 3 extensions for our data), keyed by `certification_key`:

```json
{
  "supplier_declaration_free_trade": {
    "en": "Requires Supplier Conformity Declaration (Free-Trade)",
    "ar": "يتطلب إقرار مطابقة المورّد (تجارة حرة)",
    "regulated": false
  },
  ...
}
```

The chatbot should select the phrase whose key matches `detail.certification.key` and render it in the user's language. Never generate certification text dynamically.

---

## Public API

```python
class SearchEngine:
    def __init__(data_dir: str | Path) -> None
    def search(query: str, limit: int = 10) -> list[SearchResult]
    def search_grouped(query: str, per_chapter_limit: int = 5) -> list[ChapterGroup]
    def get_by_prefix(prefix: str, limit: int = 25) -> list[SearchResult]
    def get_details(hs_code: str) -> Optional[ProductDetail]
    def get_parent(code: str, level: int) -> Optional[ParentCode]
    def chapter_label(chapter: str) -> Optional[str]
    def stats() -> dict
```

All methods are **synchronous and deterministic**. The engine loads all tables into memory on instantiation (~1.4 MB total). Searches run against in-memory dicts/lists — no I/O per query. Safe to instantiate once per bot process and call concurrently from async handlers.

### Auto-detection

`search()` and `search_grouped()` auto-detect whether the query is numeric (prefix match on HS code) or textual (substring + stemming on product names). To force one mode, use `get_by_prefix()` for numeric.

### Arabic morphology handling

The search engine applies light stemming so:

| Singular query | matches data with | Works? |
|----------------|-------------------|--------|
| `بطارية` | `بطاريات` (plural) | ✓ |
| `كهربائي` | `كهربائية` (feminine) | ✓ |
| `أجهزة` | `جهاز` (mixed forms) | partial — non-concatenative morphology |

> **Limitation**: Broken plurals like `جهاز` ↔ `أجهزة` aren't fully matched by suffix stemming alone (Arabic morphology is non-concatenative). For these cases, recommend chat users use either form, or have the LLM rephrase the query. We can add ISRI stemming in v2.

---

## How this maps to the chat ↔ PDF tier strategy

| Field | Chat tier (free, light) | PDF tier (deep, conversion artifact) |
|-------|------------------------|------------------------------------|
| HS code + product name | ✓ | ✓ |
| Parent code hierarchy | ✓ (numbers + derived desc) | ✓ + authoritative WCO desc |
| Regulation name (EN+AR) | ✓ | ✓ |
| Standard certification phrase | ✓ | ✓ |
| Regulation summary | shown if short | ✓ full |
| Step-by-step guide | — *(hooks: "available in PDF")* | ✓ |
| Estimated cost | — *(hooks: "available in PDF")* | ✓ |
| Estimated timeline | — *(hooks: "available in PDF")* | ✓ |
| Referenced standards (per HS code) | — | ✓ (use `hs_codes_standards_lookup.csv` in repo root) |
| Documents required (per regulation) | — | ✓ (use `hs_code_regulations.csv` in repo root) |
| Related parties | — | ✓ (use `hs_code_regulations.csv` in repo root) |
| List of accredited labs | — | ✓ (use `reviewed_tables/approved_bodies.csv` in repo root) |

The chat tier returns just `SearchResult` / `ProductDetail`. The PDF tier should pull the additional fields from the parent repo's master sheets (which already exist) and pipe them into `tools/generate_dynamic_pdf.py`.

---

## How to refresh data

When `saber_master.csv`, `regulations_metadata.csv`, or `hs_code_regulations.csv` is updated in the parent repo, regenerate the tables:

```bash
py -3 hs_search_tool/prepare_data.py --source-dir . --output-dir hs_search_tool/data
```

This is idempotent — safe to re-run.

---

## What's NOT in this package (intentionally)

- Telegram bot loop / handlers
- Claude API calls or other LLM orchestration
- PDF generation
- Lead capture / CRM integration
- Live web scraping

Those belong in the **consuming project** (e.g., the new RACs bot). This package is just the search backend.

---

## Status

✅ 42 / 42 tests passing
✅ 5,221 HS codes loaded
✅ 5,098 (97.6%) matched to a regulation
✅ Bilingual certification phrases (EN + AR) for all 7 keys
✅ Demo reproduces the Waleed-style disambiguation + drill-down UX
✅ No external dependencies at search time (pandas only needed for data prep)

Last verified: 2026-05-29
