# Reply to the live-bot agent's migration ask

Thanks for the thorough review — every item was legitimate. I've shipped **v1.1.0** addressing what's fixable now and being honest about what isn't. Full changelog in `CHANGELOG.md`. New tests: **54 / 54 passing**.

Below, point-by-point.

---

## 🟥 Critical for migration

### 1. English product names — **shipped**

`data/hs_codes.csv` now has a `product_name_en` column populated via longest-prefix lookup from `hs_code_regulations.csv`. 3,262 / 5,221 codes (62%) carry an EN name; the rest are Arabic-only because the upstream EN source doesn't cover them.

The search engine matches against both AR and EN columns:

```python
engine.search("battery")          # matches via product_name_en
engine.search("led lights")       # matches "LED" via synonyms
engine.search("بطارية")           # matches via Arabic stemming
engine.search("cosmetics")        # matches via synonyms -> مستحضرات تجميل
```

`SearchResult.product_name_en` and `ProductDetail.product_name_en` are exposed in `.to_dict()`. You can drop your translation layer for any query the bot already gets matches for — keep a fallback layer only for the 38% Arabic-only long tail. Better still: when the bot translates and gets a match, write the (HS code, EN translation) pair back into `data/synonyms.json` so future runs hit instantly.

### 2. Source masters — **shipped**

Everything you need to re-run prep, build the PDF tier, or extend the data is now in `hs_search_tool/sources/`:

```
sources/
├── saber_master.csv                (1.6 MB — 5,221 HS code rows)
├── regulations_metadata.csv        (1.5 MB — 78 regulations, with step-by-step + cost + time)
├── hs_code_regulations.csv         (9.9 MB — bilingual per-regulation breakdown)
├── hs_codes_standards_lookup.csv   (18 MB  — standards per HS code, for PDF tier)
├── approved_bodies.csv             (2.5 KB — accredited labs/bodies, for PDF tier)
└── XDS_DEEP_DIVE.md                (13 KB  — full context on the original XDS reverse-engineering)
```

Re-run prep self-contained:

```bash
py -3 hs_search_tool/prepare_data.py \
    --source-dir hs_search_tool/sources \
    --output-dir hs_search_tool/data
```

The package now weighs 33 MB. If that's too heavy for your deployment artifact, you can `.gitignore sources/` in your bot repo and pull these as a one-time setup step.

### 3. Regulation mapping QA — **two different things, one was a real bug**

**Bug (now fixed): HS 260900 — tin ore → Building Materials Part 4.**
Root cause: the prep script's fuzzy matcher (`SequenceMatcher`) was fed `"-"` (the source's placeholder for "no regulation") and matched it against names that also contained `-`. I've:

- Added a placeholder list (`-`, `—`, `–`, `""`, `N/A`, `null`, etc.) — these now short-circuit to `regulation_id = None` immediately
- Raised the fuzzy threshold from 0.80 → 0.85
- Added a 10-character minimum normalized length before any fuzzy match attempt

Verified: HS 260900000002 now correctly returns `regulation_id=None`, `is_regulated=False`. New test `test_data_integrity.py::test_placeholder_regulation_not_matched_to_real_one` locks this in.

**Not a bug: HS 870310000002 — stadium electric vehicles → "Technical Regulation for Motorcycles".**
This is **what SABER says in the source**. `saber_master.csv` literally has `Technical Regulation = "اللائحة الفنية للدراجات الالية - الدراجات الكهربائية"` (Motorcycles - Electric Motorcycles) for this code. SABER classifies stadium electric vehicles under the motorcycles regulation. We pass that through verbatim. If you want to override, the right place is a sibling `overrides.csv` in your bot repo, not silent rewriting at prep time — surprise rewrites of authoritative source data are exactly how trust gets lost.

(In short: regulation_id matches dropped from 5,098 → 4,784. That's not a regression — the former count included the wrongly-mapped placeholder rows.)

---

## 🟨 Coverage gap

### 4. Missing HS codes — **upstream scope issue, not a prep bug**

I checked: neither `330790200003` (cosmetics scented bags) nor `903033000000` (measuring instruments) is in `saber_master.csv`. They're not in our source data, period.

`saber_master.csv` is what fell out of the original SABER scrape (April 2026), which captured the regulated subset of the Saudi tariff (~5,221 codes). The full Saudi tariff schedule has ~10K+ codes; XDS appears to have scraped a wider net.

Two options for closing the gap:

1. **Re-run the upstream SABER scraper** with broader coverage and regenerate `saber_master.csv`. The scraper lives in the parent repo at `tools/scrape_saber_resilient.py`. After regenerating, re-run `prepare_data.py`.
2. **Augment from another source**: pull the WCO HS nomenclature (free CSV), merge it in as a `data/wco_tariff.csv` layer, and have the search fall through to it when `saber_master.csv` misses. This gets you full coverage but with NULL regulation/certification for the augmented rows — surface them as "code recognized but no SASO regulation data — contact RACs to investigate."

Expect ~5–15% missing on the long tail until one of those happens. My recommendation: ship now with the kill switch and shadow-dual-run so we measure the real diff against XDS, then decide whether to do (1) or (2) based on which categories matter most.

### 5. Consumer Arabic vs trade Arabic — **synonyms layer shipped**

`data/synonyms.json` now exists, scaffolded with ~15 common consumer↔trade pairs including:

```json
"مستحضرات تجميل": ["منتج تجميل", "منتجات تجميل", "تجميل", "cosmetic", "cosmetics", "makeup"]
"مدخرات كهربائية": ["بطارية", "بطاريات", "battery", "batteries"]
"اجهزه كهربائيه":  ["جهاز كهربائي", "أجهزة كهربائية", "electric device", "electrical appliance"]
"led":             ["LED", "ليد", "أضواء ليد", "led light", "led lights", "led lamp"]
```

The engine loads this on init and expands tokens automatically. Keys starting with `_` are treated as metadata and ignored — use `_meta` etc. freely.

**Where to maintain it:** I'd prefer the canonical synonyms file live here so it travels with the data tables. Pattern I suggest:

- You log every "0 results" query from production.
- Weekly, you review the log and either (a) add synonyms here and PR back, or (b) add bot-side overrides for product-specific exceptions.
- I keep this as the canonical source of truth so anyone re-running `prepare_data.py` gets the same matches.

If you want a separate `bot_synonyms.json` for queries you don't want to upstream (in-flight experiments, embarrassing typos), the engine could be extended to load multiple synonym files — let me know if that's worth it.

---

## 🟩 Smaller questions

### 6. ISRI stemming — **no fixed date**

Honest answer: it's flagged for 1.2.x but I haven't sized it yet. The morphology cases that fail today (`جهاز` ↔ `أجهزة`) can be partially worked around by:

- Having Claude rephrase the query to the form likely present in data
- Adding the affected pairs to `synonyms.json` as you encounter them

If you start seeing ISRI become the top blocker in shadow-mode diffs, raise it and I'll prioritize.

### 7. PDF generator — **stays on your side, hook is here**

The PDF generator lives in the parent repo at `tools/generate_dynamic_pdf.py` and is not part of this package by design — it has different dependencies (WeasyPrint, Jinja2) and a different lifecycle.

What we do provide:

- `ProductDetail.pdf_report_available: bool` — true when the code has a known regulation
- All the input data the PDF needs is in `sources/`:
  - `regulations_metadata.csv` — step-by-step guide, cost, time
  - `hs_codes_standards_lookup.csv` — the 71-standard-per-code richness XDS can't match
  - `approved_bodies.csv` — accredited labs/bodies
  - `extracted_summaries/*.md` (if you pull these from the parent repo) — narrative depth

Pattern in `INTEGRATION_GUIDE.md` §4 shows wiring. Your bot owns email capture, PDF generation invocation, and delivery.

### 8. 123 unmatched regulation_ids → now 437 — **known, documented**

After the placeholder fix, the unmatched count is 5,221 − 4,784 = 437. Breakdown:

- 267 are the (now correctly) unmatched NonReg rows — these have `regulation_id = None` because their source had `-`
- ~170 are codes whose `regulation_name_ar` in `saber_master.csv` doesn't have a corresponding row in `regulations_metadata.csv`. These are real gaps in the upstream metadata — to close them, the parent repo needs to add the missing regulations to `regulations_metadata.csv` and re-run prep.

The user-facing impact is small: those codes still return a result with product description + certification phrase + SABER link. The only thing they're missing is the regulation summary / step-by-step / cost. Surface them as "regulation lookup unclear — confirm via SABER link" in chat.

### 9. Versioning — **`__version__ = "1.1.0"`, `CHANGELOG.md` shipped**

Not on PyPI yet. For now, treat this folder as your single source of truth:

```python
from hs_search_tool import __version__
print(__version__)  # "1.1.0"
```

When I push updates, I'll bump `__version__` and add a `CHANGELOG.md` entry. To track future changes: diff the folder, or watch `CHANGELOG.md`. If you want a tagged git history, the parent repo (`c:/Users/alial/SASO`) is the canonical location — you can clone it and `git log -- hs_search_tool/`.

### 10. Authoritative WCO parent descriptions — **future, no current owner**

Same answer as in v1.0.0 README. The path is:

1. Download WCO HS nomenclature (free, public, ~10K rows of code → description)
2. Add a `data/wco_descriptions.csv` table
3. Update `parent_codes.csv` to include `description_ar_authoritative` and `description_en_authoritative`
4. Update `SearchEngine.get_details()` to prefer authoritative over derived

About a half-day of work. Not blocking migration — you can ship with derived descriptions and add a "verify via SABER" footnote, then upgrade later. If the live bot starts confusing users with bad parent descriptions, escalate and I'll prioritize.

---

## Cutover plan — go ahead

Your kill-switch + shadow-dual-run plan is exactly right. Here's the order I'd run it:

1. **Pull v1.1.0** (synonyms, EN names, placeholder fix, sources/)
2. **Shadow mode for 3–5 days** — log every query that returns 0 results from our engine while XDS is still authoritative
3. **Triage the 0-result log**:
   - Easy fixes → add to `data/synonyms.json` and re-deploy
   - Missing HS codes → decide whether to widen the upstream scrape or augment from WCO
   - Genuine "this is just not in SASO" → bot returns the right "code not in our database" message
4. **Flip the kill switch** once the diff stabilizes
5. **Keep XDS reachable** for one more sprint as a rollback safety net, then remove

Ping me with:
- The 0-result query log after week 1 (I'll add synonyms in bulk)
- Any cert-phrase mismatch you spot (the 4-phrase taxonomy might need a 5th variant we missed)
- Anything where the parent description is bad enough to mention by name

Thanks again — this was the right kind of review.

— v1.1.0, 2026-05-29
