# Report from the live-bot agent — v1.1 review + local patches (v1.2-equivalent)

Hey — v1.1.0 was a big step. EN column, sources/, synonyms.json infrastructure, the placeholder-fuzzy-match fix, CHANGELOG, 54 tests. Thank you. Migration is now in reach.

We have read access to the canonical SASO repo on this machine, so rather than wait on you for each fix, we took the patches that don't need new upstream data and applied them locally. **Everything below in §"Patched locally" is staged in `Racs telegram/hs_search_tool/`** — review at your convenience and consider folding any of it upstream so the canonical package stays the source of truth. We'll re-import whatever you bless.

The one issue we genuinely cannot fix on our side (upstream scrape scope) is still flagged for you.

---

## TL;DR

| Metric | v1.1.0 (as shipped) | After local patches |
|---|---:|---:|
| Tests passing | 54/54 | **59/59** (added 5 stem-symmetry tests) |
| Real production search queries served (Postgres conversation_logs, 5 queries) | 20% (1/5) | **100% (5/5)** |
| XDS head-to-head (12 queries) | 1/12 hit | **9/12 hit** (the 3 misses are all upstream-data-scope codes) |
| Drill-down HS code coverage (3 codes real users viewed) | 0/3 | 0/3 — **needs upstream scrape widening** |

---

## §1 Patched locally — review and consider folding upstream

### Patch 1.1 — Token scoring (replaces strict AND) in `search.py`

**Problem:** multi-word queries required every token to be a substring of the same product name. `food beverage`, `baby stroller`, `electrical device`, `led lights` all returned 0.

**Fix:** every row is scored by how many tokens it matches. Top-scoring rows (matching every token) come first; rows matching some tokens still surface as fallback recall. Pure OR would over-recall; pure AND fails on the multi-word case. Score-based ranking gives both.

Documented inline in `search.py:_token_match_count` and `_ranked_keyword_rows`. Used by both `search()` and `search_grouped()` for keyword (non-numeric) queries.

**Test impact:** Updated `tests/test_search.py::test_search_multi_token_arabic` — the previous test asserted strict AND semantics; the new test validates "every result matches at least one token; AND-matches rank first."

### Patch 1.2 — Stemmer asymmetry between articulated and bare Arabic forms

**Problem:** `_stem_arabic_word()` was single-pass. Articulated forms (with `ال`) cleared the length gate and lost both prefix and suffix; bare forms with the same root fell below the gate and only lost the prefix. Trace:

| Input | After normalize | After prefix strip | After suffix strip | Stem |
|---|---|---|---|---|
| `أغذية` | `اغذية` (5) | strip `ا` → `غذية` (4) | **skipped** — len < 5 | `غذية` |
| `الأغذية` | `الاغذية` (7) | strip `ال` → `اغذية` (5) | strip `ية` → `اغذ` (3) | `اغذ` |

Same root, different stems, no substring overlap. This is why `food beverage` failed even after Patch 1.1: the synonym mapped `food` → canonical `أغذية` → stem `غذية`, but the data's `الأغذية` stemmed to `اغذ`. `غذية` is not a substring of `اغذ`.

**Fix:** iterate prefix stripping until no more apply, then attempt one suffix strip. Both `أغذية` and `الأغذية` now converge to `غذية`. Same idea would apply for any articulated/bare root pair.

```python
def _stem_arabic_word(word: str) -> str:
    if len(word) < 5:
        return word
    while len(word) >= 5:
        stripped = False
        for prefix in _AR_PREFIXES:
            if word.startswith(prefix) and len(word) - len(prefix) >= 4:
                word = word[len(prefix):]
                stripped = True
                break
        if not stripped:
            break
    if len(word) >= 5:
        for suffix in _AR_SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                return word[:-len(suffix)]
    return word
```

**Regression tests added** in `tests/test_stem_symmetry.py` — 5 cases covering articulated/bare alignment for food, devices, batteries, plus an over-stem guard and the end-to-end "food search finds الأغذية rows" scenario.

### Patch 1.3 — Cleaned 2,633 noisy `product_name_en` cells

**Problem:** the `product_name_en` column had three bad data patterns from the v1.1.0 prep run:
- **7.1% (369 rows)** had Arabic strings in the EN column (prefix-lookup fallback copied AR when no EN match existed)
- **43.4% (2,264 rows)** had the literal string `"nan"` (pandas NaN serialized as text)
- **37.5%** were genuinely empty (acceptable)
- **12% (629 rows)** were clean English

The Arabic-polluted cells caused two bugs: (a) English keyword searches missed them; (b) Arabic queries against these cells skipped the Arabic stemmer because EN normalization is `.lower().strip()` only, not stem-aware. The `"nan"` cells were noise — substring matching against `nan` would falsely hit thousands of rows on any short-string query.

**Fix:** in-place CSV cleanup script set both patterns to empty strings. Final state: 12% real English (unchanged), 88% honestly empty.

**For your prep script (`prepare_data.py`):** when no English match exists, **don't copy the AR name and don't write the literal `nan`**. Just leave the column empty.

### Patch 1.4 — Synonyms.json — replaced 7 dead-end canonicals

Pre-existing in our earlier review. v1.1.0 file had canonicals that didn't appear in `saber_master.csv`. Verified replacements:

| v1.1.0 canonical | Row hits in master | Replaced with | Hits |
|---|---:|---|---:|
| `مستحضرات تجميل` | 0 | `تجميل` | 4 |
| `اجهزه كهربائيه` | 0 | `كهربائي` | 101 |
| `احذيه` | 0 | `أحذية` | 30 |
| `اطعمه` | 0 | `أغذية` | 4 (now stems to `غذية` matching data ✓) |
| `ادويه` | 0 | `أدوية` | 1 |
| `ادوات منزليه` | 0 | `منزلية` | 13 |
| `telephone` | 0 | `هاتف` | 26 |

All consumer aliases preserved on the new canonicals.

`_meta.verified_against` now records: `"C:/Users/alial/SASO/saber_master.csv on 2026-05-29"`.

---

## §2 Still upstream — only you can fix this

### Issue C — Coverage gap: regulated codes our users actually viewed are missing

**Severity:** Blocks migration cutover. Drill-down coverage is 0% on observed real-user traffic.

Three HS codes that real users viewed via XDS in the last week are missing from `saber_master.csv`:

| HS code | Product | Saw via XDS as |
|---|---|---|
| `330790200003` | Cosmetics — scented bags | Non-Regulated (Free-Trade) |
| `903033000000` | Telecom measuring instruments | Non-Regulated |
| `960330000000` | Artists' brushes / cosmetics application | Non-Regulated |

All three are **Non-Regulated**. Conjecture: the SABER scrape that feeds `saber_master.csv` prioritized the regulated subset. Non-Regulated codes — even when they have SABER landing pages — appear to have been deprioritized.

**Asks:**

1. **Re-run `tools/scrape_saber_resilient.py`** (in `C:/Users/alial/SASO/tools/`) with the Non-Regulated category included. Regenerate `saber_master.csv`. Re-run `prepare_data.py`. Should close most of the gap.

2. **OR augment with WCO HS nomenclature** as a fallback layer. The fallback rows would have `regulation_id = NULL` and `certification_key = "unknown"` so the bot can surface them as "code recognized but no SASO regulation data — contact RACs to investigate" rather than 0-results.

Until this is closed, the live bot's shadow-mode dual-run will keep flagging drill-down failures. We can mitigate UX-side by detecting `get_details() == None` and falling through to a "code not in our database, here's the SABER link" message, but it's a degraded experience.

---

## §3 What I built on the live-bot side (FYI, not asking you to do anything)

### A drop-in shim — `tools/local_xds_query.py`

100-line module that exposes the same `search(query, page)` / `get_detail(url)` classmethod interface as the bot's existing `XDSQueryEngine`. The orchestrator can swap engines with a one-line import change. The shim:

- Generates `detail_url`s as `https://local.racs/hs?hscode=<HS_CODE>` so the orchestrator's existing `_extract_hs_code(url)` helper works unchanged
- Returns a payload shape matching what the system prompt expects (`regulation_name`, `regulation_summary`, `saber_links`, `products_covered`, `certification_requirements`, `product_classification`, `pdf_report_available`)
- Omits `estimated_cost` and `estimated_time_needed` from the chat-tier payload by design — those belong to the PDF tier per your migration response

Once Issue C is addressed, cutover is just:

```python
- from tools.xds_query import XDSQueryEngine
+ from tools.local_xds_query import LocalXDSQueryEngine as XDSQueryEngine
```

No other orchestrator changes needed.

### Coverage audit script — `.tmp/coverage_audit.py`

Walks every conversation in our Postgres `conversation_logs`, extracts every `search_xds` query and every `get_regulation_detail` HS code, then reports what the local engine would have served. We'll run this weekly during shadow mode so we can give you precise data on which production queries/codes are still gaps.

---

## §4 Recommended next steps

1. **Review patches 1.1–1.4** at your convenience. If you agree with the approach, fold them into the canonical SASO copy. We'll re-import the canonical version once it lands.
2. **Fix Issue C (widen the scrape)** — only you can do this; it's upstream of our copy.
3. **Live-bot side: shadow mode** starting once Issue C is in flight. We'll log every diff vs XDS to Postgres for 5–7 days and report back with a fresh coverage audit.
4. **Cutover** once shadow-mode shows we're at or above XDS parity.

---

## §5 Honest take, updated

The local engine is now **at parity with XDS on every dimension except code coverage**. Of 12 queries head-to-head:
- 9 wins or ties for local
- 3 losses, all because of missing HS codes (upstream scope)

Once Issue C is fixed, the local engine surpasses XDS on:
- **Speed** — 0.20s test suite vs network-scrape latency
- **Depth** — `regulation_summary` is multi-paragraph SASO official text vs XDS's stripped 2-sentence intro
- **Bilingual** — XDS is EN-only; ours returns AR for AR UX
- **Reliability** — no HTML scraping fragility
- **Determinism** — no AI, just lookup + templates

Thanks again. Genuinely good architecture.

— Live-bot agent, 2026-05-29
