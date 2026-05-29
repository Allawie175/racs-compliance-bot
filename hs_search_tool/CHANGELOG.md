# Changelog

All notable changes to `hs_search_tool` will be documented here. Versioning follows semver. The version constant lives in `__init__.py`.

---

## [1.1.0] — 2026-05-29

**Migration-feedback release.** Responds to the live-bot agent's review of v1.0.0.

### Added
- **English product names** in `data/hs_codes.csv` (new `product_name_en` column). Populated via longest-prefix lookup from `hs_code_regulations.csv`. 3,262 / 5,221 codes (62%) now carry an English name; the rest are Arabic-only because our master data doesn't have EN equivalents for them yet.
- **English keyword search**: `engine.search("battery")` now matches rows whose `product_name_en` contains the term. Search compares the query against both AR (stemmed) and EN (lowercased) columns.
- **Synonyms layer**: `data/synonyms.json`. Bilingual canonical→synonyms map. Currently scaffolded with ~15 common product categories (cosmetics, batteries, vehicles, footwear, LED, scooter, etc.). Extend as you learn from real queries.
- **`product_name_en` on `SearchResult` and `ProductDetail`** — exposed in `.to_dict()` output.
- **`sources/` directory** with the source CSVs and `XDS_DEEP_DIVE.md` so the package is fully self-contained. `prepare_data.py` can now be re-run from the package alone without needing the parent repo:
  ```
  py -3 hs_search_tool/prepare_data.py --source-dir hs_search_tool/sources --output-dir hs_search_tool/data
  ```
- **New tests**: `test_english_search.py`, `test_synonyms.py`, `test_data_integrity.py`. Total now 54 / 54 passing.

### Fixed
- **Placeholder regulation bug** (the live agent caught this). Source rows with `Technical Regulation = "-"` (267 NonReg codes) were being fuzzy-matched to unrelated regulations. They now correctly carry `regulation_id = None` and `is_regulated = False`. Verified on HS 260900000002 (tin ore).
- **Fuzzy-match threshold** raised from 0.80 → 0.85 to cut false positives. Also requires the source name to be ≥10 normalized characters before any fuzzy match is attempted.

### Changed
- `with_regulation_id` count dropped from 5,098 (97.6%) to 4,784 (91.7%). This is a **correctness improvement**, not a regression — the previous higher count included the wrongly-mapped placeholder rows.
- Loading-stats test threshold lowered from 95% to 90% to reflect the corrected mapping.

### Known limitations (carried forward from 1.0.0)
- **Broken-plural Arabic morphology**: `جهاز` ↔ `أجهزة` partial. ISRI stemming planned for 1.2.x.
- **Some HS codes missing** vs SASO's full tariff schedule. Our base is `saber_master.csv` which has 5,221 codes; full SASO tariff has ~10K+. This is an **upstream data scope** issue, not a prep bug. To extend coverage, the parent repo's scraper needs to widen its source.
- **Parent code descriptions are derived** from sibling rows. Authoritative WCO descriptions (per HS nomenclature) are still pending.
- **Source data quality**: SABER's own classification of some products is questionable (e.g., HS 870310 stadium electric vehicles classified under the Motorcycles regulation). We pass through the source verbatim; we don't second-guess SASO.
- **PDF generator not in this package**. Lives in the parent repo at `tools/generate_dynamic_pdf.py`. We expose `pdf_report_available` as a hook; the consuming project owns generation.

---

## [1.0.0] — 2026-05-29

Initial release.

- `SearchEngine` with `search()`, `search_grouped()`, `get_details()`, `get_by_prefix()`, `get_parent()`, `chapter_label()`, `stats()`
- 5,221 HS codes, 78 regulations, 3,093 parent codes
- 7 standard certification phrases (EN+AR)
- Arabic stemming for plural/singular tolerance
- Tree-grouped disambiguation by HS chapter
- 42 / 42 tests passing
- Demo reproduces the Waleed conversation flow
