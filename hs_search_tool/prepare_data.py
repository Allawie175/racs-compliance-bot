"""
Data preparation script for HS search tool.

Reads the SASO master sheets and produces three clean, optimized tables:
  - data/hs_codes.csv          (one row per HS code, with denormalized regulation info)
  - data/regulations.csv       (one row per regulation)
  - data/parent_codes.csv      (one row per 4-digit and 6-digit parent)
  - data/certification_phrases.json  (Scraped_From -> standard phrase mapping)

Run from repo root:
    py -3 hs_search_tool/src/prepare_data.py --source-dir . --output-dir hs_search_tool/data

Re-run any time the master sheets are updated.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd


def normalize_arabic(text: str) -> str:
    """Normalize Arabic text for fuzzy comparison.

    Strips diacritics/tatweel, unifies alef/yaa/taa-marbouta variants,
    collapses whitespace, removes RTL/LTR marks, lowercases ASCII.
    """
    if not text:
        return ""
    s = str(text).strip()
    s = "".join(s.split())  # remove all whitespace
    s = s.replace("ـ", "")  # tatweel
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ى", "ي")
    s = s.replace("ة", "ه")
    s = s.replace("‏", "").replace("‎", "").replace("‏", "").replace("‎", "")
    return s.lower()


# Maps the saber_master Scraped_From column to one of the 5 canonical
# certification phrases (4 from XDS + 1 multi-route variant we observed).
SCRAPED_FROM_TO_PHRASE = {
    "NonReg": "supplier_declaration_free_trade",
    "PCoC|QM": "saber_coc_or_qm",
    "QM": "quality_mark_only",
    "QM|TireLabel": "saber_coc_or_qm",
    "COC-CST": "saber_coc_or_qm",
    "G-Mark|QM": "gcts_or_qm",
    "G-Mark|PCoC|QM": "gcts_or_qm",
    "IECEE|PCoC|QM": "multi_route",
    "IECEE|QM": "multi_route",
    "CITC-Conf|IECEE|QM": "multi_route",
    "G-Mark|IECEE|PCoC|QM": "multi_route",
    "OxoBio|QM": "saber_coc_or_qm",
    "TypeApproval": "type_approval",
}

CERTIFICATION_PHRASES = {
    "supplier_declaration_free_trade": {
        "en": "Requires Supplier Conformity Declaration (Free-Trade)",
        "ar": "يتطلب إقرار مطابقة المورّد (تجارة حرة)",
        "regulated": False,
    },
    "saber_coc_or_qm": {
        "en": "Requires Saber Certificate of Conformity or Quality Mark Certificate",
        "ar": "يتطلب شهادة مطابقة سابر أو شهادة علامة الجودة",
        "regulated": True,
    },
    "quality_mark_only": {
        "en": "Requires Quality Mark Certificate",
        "ar": "يتطلب شهادة علامة الجودة",
        "regulated": True,
    },
    "gcts_or_qm": {
        "en": "Requires GCTS Certificate or Quality Mark Certificate",
        "ar": "يتطلب شهادة GCTS أو شهادة علامة الجودة",
        "regulated": True,
    },
    "multi_route": {
        "en": "Requires Saber Certificate of Conformity or GCTS Certificate or IECEE Certificate or Quality Mark Certificate",
        "ar": "يتطلب شهادة مطابقة سابر أو شهادة GCTS أو شهادة IECEE أو شهادة علامة الجودة",
        "regulated": True,
    },
    "type_approval": {
        "en": "Requires Type Approval Certificate",
        "ar": "يتطلب شهادة الموافقة على النوع",
        "regulated": True,
    },
    "unknown": {
        "en": "Certification requirement unclear — please contact RACs for verification",
        "ar": "متطلبات الشهادة غير واضحة — يرجى التواصل مع راكس للتحقق",
        "regulated": True,
    },
}


def normalize_hs_code(code) -> str | None:
    """Cast HS code to a clean numeric string. Returns None for unparseable."""
    if pd.isna(code):
        return None
    s = str(code).strip()
    if not s or s == "-":
        return None
    digits = "".join(c for c in s if c.isdigit())
    return digits or None


def load_saber_master(source_dir: Path) -> pd.DataFrame:
    path = source_dir / "saber_master.csv"
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    df["hs_code"] = df["HS Code"].apply(normalize_hs_code)
    df = df[df["hs_code"].notna()].copy()
    df["product_name_ar"] = df["Product Name"].fillna("").astype(str).str.strip()
    df["regulation_name_ar"] = df["Technical Regulation"].fillna("").astype(str).str.strip()
    df["certificates_ar"] = df["Certificates"].fillna("").astype(str).str.strip()
    df["scraped_from"] = df["Scraped_From"].fillna("").astype(str).str.strip()
    return df[["hs_code", "product_name_ar", "regulation_name_ar", "certificates_ar", "scraped_from"]]


def load_regulations_metadata(source_dir: Path) -> pd.DataFrame:
    path = source_dir / "regulations_metadata.csv"
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    keep = [
        "Code",
        "Regulation_Name_AR",
        "Summary",
        "Step_by_Step_Guide",
        "Estimated_Cost",
        "Estimated_Time_Needed",
        "Confidence_Score",
        "PDF_Link",
    ]
    keep = [c for c in keep if c in df.columns]
    df = df[keep].copy()
    df = df.rename(columns={
        "Code": "regulation_id",
        "Regulation_Name_AR": "regulation_name_ar",
        "Summary": "summary",
        "Step_by_Step_Guide": "step_by_step_guide",
        "Estimated_Cost": "estimated_cost",
        "Estimated_Time_Needed": "estimated_time_needed",
        "Confidence_Score": "confidence_score",
        "PDF_Link": "pdf_link",
    })
    return df


def load_hs_code_regulations(source_dir: Path) -> pd.DataFrame:
    """Bilingual regulation metadata keyed by REG_ID."""
    path = source_dir / "hs_code_regulations.csv"
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    # One row per REG_ID is enough for EN name lookup
    bilingual = (
        df.dropna(subset=["REG_ID", "Regulation_Name", "Regulation_Name_AR"])
        .drop_duplicates(subset=["REG_ID"], keep="first")
        [["REG_ID", "Regulation_Name", "Regulation_Name_AR"]]
        .rename(columns={
            "REG_ID": "reg_id_numeric",
            "Regulation_Name": "regulation_name_en",
            "Regulation_Name_AR": "regulation_name_ar",
        })
    )
    bilingual["reg_id_numeric"] = bilingual["reg_id_numeric"].apply(
        lambda x: str(x).strip().zfill(3) if pd.notna(x) else None
    )
    return bilingual


def build_regulation_table(
    metadata: pd.DataFrame,
    bilingual: pd.DataFrame,
) -> pd.DataFrame:
    """Merge regulations_metadata + hs_code_regulations to get EN+AR names."""
    metadata = metadata.copy()
    metadata["reg_id_numeric"] = metadata["regulation_id"].str.extract(r"REG-(\d+)")
    merged = metadata.merge(
        bilingual[["reg_id_numeric", "regulation_name_en"]],
        on="reg_id_numeric",
        how="left",
    )
    # Slug from regulation_id: REG-030 -> reg-030
    merged["slug"] = merged["regulation_id"].str.lower()
    return merged.drop(columns=["reg_id_numeric"])


def derive_certification_key(scraped_from: str) -> str:
    """Map a Scraped_From token to a certification phrase key."""
    if not scraped_from:
        return "unknown"
    return SCRAPED_FROM_TO_PHRASE.get(scraped_from, "unknown")


def match_regulation_id(reg_name_ar: str, regulations: pd.DataFrame) -> str | None:
    """Map an Arabic regulation name from saber_master to a REG-XXX id."""
    if not reg_name_ar or reg_name_ar == "-":
        return None
    reg_name_ar = reg_name_ar.strip()
    for _, row in regulations.iterrows():
        ref = str(row.get("regulation_name_ar", "")).strip()
        if ref and (ref == reg_name_ar or ref in reg_name_ar or reg_name_ar in ref):
            return row["regulation_id"]
    return None


def load_hs_code_regulations_full(source_dir: Path) -> pd.DataFrame:
    """Load hs_code_regulations.csv with all columns for EN-name lookup."""
    path = source_dir / "hs_code_regulations.csv"
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    return df


# Placeholder strings that earlier versions wrongly fuzzy-matched as regulations.
# Treat as "no regulation" — never attempt to match these to a REG-XXX id.
_PLACEHOLDER_REGULATION_NAMES = {"", "-", "—", "–", "N/A", "NA", "null", "None", "غير محدد"}


def build_hs_code_table(
    master: pd.DataFrame,
    regulations: pd.DataFrame,
    hcr_full: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Produce the final HS codes table with regulation FK + cert key + EN name.

    Matching strategy (regulation):
      0. Skip if regulation_name_ar is a placeholder ("-", empty, etc.)
      1. Exact match on normalized Arabic
      2. Substring containment on normalized Arabic (longest wins)
      3. SequenceMatcher ratio >= 0.85 (raised from 0.80 to cut false positives)

    EN product name strategy:
      Look up product_name_en from hs_code_regulations.csv by descending-length
      prefix match. HS 850710000009 inherits from row 850710 if present,
      else 8507, else None.
    """
    # Build normalized lookup: normalized name -> regulation_id
    reg_entries: list[tuple[str, str, str]] = []  # (regulation_id, raw_name, normalized_name)
    for _, row in regulations.iterrows():
        rid = row["regulation_id"]
        raw = str(row.get("regulation_name_ar", "") or "").strip()
        if rid and raw:
            reg_entries.append((rid, raw, normalize_arabic(raw)))

    exact_lookup = {n: rid for rid, _, n in reg_entries}

    def match_one(name_ar: str) -> str | None:
        if not name_ar:
            return None
        cleaned = str(name_ar).strip()
        if cleaned in _PLACEHOLDER_REGULATION_NAMES:
            return None
        target = normalize_arabic(cleaned)
        # Reject targets too short to match meaningfully
        if not target or len(target) < 10:
            return None
        # 1. exact normalized
        if target in exact_lookup:
            return exact_lookup[target]
        # 2. substring (longest matching reg wins)
        candidates = [(rid, n) for rid, _, n in reg_entries
                      if n and (n in target or target in n)]
        if candidates:
            candidates.sort(key=lambda x: len(x[1]), reverse=True)
            return candidates[0][0]
        # 3. fuzzy ratio (>=0.85)
        best_rid, best_ratio = None, 0.0
        for rid, _, n in reg_entries:
            if not n:
                continue
            r = SequenceMatcher(None, target, n).ratio()
            if r > best_ratio:
                best_ratio, best_rid = r, rid
        return best_rid if best_ratio >= 0.85 else None

    # Build per-unique-name cache to avoid recomputing for the 5K rows
    unique_names = master["regulation_name_ar"].dropna().unique()
    name_to_rid = {n: match_one(n) for n in unique_names}

    # Build EN-name lookup keyed by HS code prefix (longest first when filling)
    en_by_prefix: dict[str, str] = {}
    if hcr_full is not None and not hcr_full.empty:
        for _, row in hcr_full.iterrows():
            code = str(row.get("HS_Code", "") or "").strip()
            digits = "".join(c for c in code if c.isdigit())
            en = str(row.get("Product_Sub_Type", "") or "").strip()
            if digits and en and digits not in en_by_prefix:
                en_by_prefix[digits] = en

    def lookup_en(hs_code: str) -> str:
        if not hs_code:
            return ""
        for length in (12, 10, 8, 6, 4):
            if len(hs_code) >= length:
                prefix = hs_code[:length]
                if prefix in en_by_prefix:
                    return en_by_prefix[prefix]
        return ""

    master = master.copy()
    master["regulation_id"] = master["regulation_name_ar"].map(name_to_rid)
    master["certification_key"] = master["scraped_from"].apply(derive_certification_key)
    master["parent_4"] = master["hs_code"].str[:4]
    master["parent_6"] = master["hs_code"].str[:6]
    master["chapter"] = master["hs_code"].str[:2]
    master["product_name_en"] = master["hs_code"].apply(lookup_en)
    return master[[
        "hs_code", "chapter", "parent_4", "parent_6",
        "product_name_ar", "product_name_en",
        "regulation_id", "regulation_name_ar",
        "certification_key", "scraped_from",
    ]]


def build_parent_codes_table(hs_codes: pd.DataFrame) -> pd.DataFrame:
    """For each unique parent (4-digit and 6-digit), pick a representative description.

    Strategy: take the most common product_name_ar for codes sharing that prefix,
    truncated to a representative phrase. Mark all entries as 'derived' so the
    consumer knows these aren't authoritative WCO descriptions.
    """
    parents: list[dict] = []
    for level, col in [(4, "parent_4"), (6, "parent_6")]:
        for prefix, group in hs_codes.groupby(col):
            if not prefix or pd.isna(prefix):
                continue
            descriptions = group["product_name_ar"].dropna().tolist()
            descriptions = [d for d in descriptions if d and d.strip() not in ("", "-")]
            if descriptions:
                most_common = Counter(descriptions).most_common(1)[0][0]
                # Strip leading "ـ ـ ـ" dashes common in Arabic HS texts
                rep = most_common.lstrip(" ـ–-").strip()
            else:
                rep = ""
            regulations = group["regulation_id"].dropna().unique().tolist()
            parents.append({
                "code": prefix,
                "level": level,
                "description_ar_derived": rep,
                "child_count": len(group),
                "regulation_ids": "|".join(sorted(set(regulations))) if regulations else "",
            })
    return pd.DataFrame(parents).sort_values(["level", "code"]).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path("."),
                        help="Directory containing saber_master.csv etc. (default: cwd)")
    parser.add_argument("--output-dir", type=Path, default=Path("hs_search_tool/data"),
                        help="Where to write the prepared CSVs and JSON (default: hs_search_tool/data)")
    args = parser.parse_args(argv)

    source = args.source_dir.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    print(f"[prepare] source={source}")
    print(f"[prepare] output={output}")

    # 1. Load source tables
    print("[prepare] loading saber_master.csv...")
    master = load_saber_master(source)
    print(f"[prepare]   {len(master):,} HS code rows")

    print("[prepare] loading regulations_metadata.csv...")
    metadata = load_regulations_metadata(source)
    print(f"[prepare]   {len(metadata)} regulation metadata rows")

    print("[prepare] loading hs_code_regulations.csv for EN names...")
    bilingual = load_hs_code_regulations(source)
    print(f"[prepare]   {len(bilingual)} bilingual regulation entries")

    print("[prepare] loading hs_code_regulations.csv (full) for EN product names...")
    hcr_full = load_hs_code_regulations_full(source)
    en_coverage = hcr_full["Product_Sub_Type"].notna().sum() if "Product_Sub_Type" in hcr_full.columns else 0
    print(f"[prepare]   {len(hcr_full)} rows, {en_coverage} with English product names")

    # 2. Build regulations table (with EN names merged in)
    regulations = build_regulation_table(metadata, bilingual)
    print(f"[prepare] regulations table: {len(regulations)} rows")

    # 3. Build HS codes table (with FK to regulation + cert key + EN name)
    hs_codes = build_hs_code_table(master, regulations, hcr_full)
    matched = hs_codes["regulation_id"].notna().sum()
    en_filled = (hs_codes["product_name_en"].fillna("").str.len() > 0).sum()
    print(f"[prepare] hs_codes table: {len(hs_codes):,} rows ({matched:,} with regulation_id, {en_filled:,} with EN name)")

    # 4. Build parent codes table
    parents = build_parent_codes_table(hs_codes)
    print(f"[prepare] parent_codes table: {len(parents)} rows")

    # 5. Write outputs
    hs_codes.to_csv(output / "hs_codes.csv", index=False, encoding="utf-8")
    regulations.to_csv(output / "regulations.csv", index=False, encoding="utf-8")
    parents.to_csv(output / "parent_codes.csv", index=False, encoding="utf-8")
    with open(output / "certification_phrases.json", "w", encoding="utf-8") as f:
        json.dump(CERTIFICATION_PHRASES, f, ensure_ascii=False, indent=2)

    print(f"\n[prepare] wrote:")
    for name in ("hs_codes.csv", "regulations.csv", "parent_codes.csv", "certification_phrases.json"):
        p = output / name
        print(f"  {p.relative_to(source)}  ({p.stat().st_size:,} bytes)")

    # Print certification mix summary so user can audit
    print("\n[prepare] certification key distribution:")
    print(hs_codes["certification_key"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
