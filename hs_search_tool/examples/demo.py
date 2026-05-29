"""
Live demo: reproduces the Waleed conversation flow using only the search engine.

Run:
    py -3 hs_search_tool/examples/demo.py

This script does NOT call any LLM. It demonstrates that the data + search API
alone can power the full disambiguation + drill-down + structured-response UX
shown in the reference conversation. The chat agent's job is just to wrap
these results in natural language.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

# Force UTF-8 stdout so Arabic + emoji render correctly on Windows consoles
# (otherwise cp1256 mangles Arabic and chokes on emoji).
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Make the package importable from anywhere
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hs_search_tool import SearchEngine


def header(text: str) -> None:
    print()
    print("=" * 80)
    print(text)
    print("=" * 80)


def render_disambiguation(engine: SearchEngine, query: str, user_name: str) -> None:
    """Reproduce the 'I found several options' menu from the sample conversation."""
    results = engine.search(query, limit=10)
    if not results:
        print(f"عذراً يا {user_name}، لم أجد نتائج للبحث: {query!r}")
        return

    print(f"وجدت عدة نتائج في قاعدة بياناتنا يا {user_name}. هل يمكنك تحديد المنتج بدقة؟ إليك ما وجدته:\n")
    for i, r in enumerate(results, 1):
        # Truncate long Arabic descriptions for readability in the menu
        desc = r.product_name_ar
        if len(desc) > 80:
            desc = desc[:77] + "..."
        print(f"الخيار {i}: {r.hs_code} — {desc}")
    print(f"\nأي من هذه الخيارات يصف منتجك بشكل أدق؟")


def render_grouped_disambiguation(engine: SearchEngine, query: str, user_name: str) -> None:
    """Tree-grouped menu: show chapters first, let user drill in."""
    groups = engine.search_grouped(query, per_chapter_limit=3)
    if not groups:
        print(f"عذراً يا {user_name}، لم أجد نتائج للبحث: {query!r}")
        return

    print(f"وجدت نتائج موزعة على عدة فئات يا {user_name}. أيها الأقرب لمنتجك؟\n")
    for g in groups[:6]:
        print(f"📂 الفصل {g.chapter} — {g.chapter_label}  ({g.count} نتيجة)")
        for r in g.results:
            desc = r.product_name_ar[:60]
            if len(r.product_name_ar) > 60:
                desc += "..."
            print(f"   └─ {r.hs_code} — {desc}")
        print()


def render_detail(engine: SearchEngine, hs_code: str, user_name: str) -> None:
    """Reproduce the structured detail response from the sample conversation."""
    detail = engine.get_details(hs_code)
    if detail is None:
        print(f"عذراً، لم أجد هذا الكود: {hs_code}")
        return

    cert = detail.certification
    print(f"📏 {detail.product_name_ar}")
    print(f"HS: {detail.hs_code}")
    print()

    # Parent hierarchy (the tree)
    print(f"   ▸ {detail.parent_4} — {detail.parent_4_description or '(وصف غير متوفر)'}")
    print(f"      ▸ {detail.parent_6} — {detail.parent_6_description or '(وصف غير متوفر)'}")
    print(f"         ▸ {detail.hs_code} — {detail.product_name_ar[:70]}")
    print()

    # Regulation block
    if detail.regulation:
        reg = detail.regulation
        if reg.name_ar:
            print(f"📋 اللائحة: {reg.name_ar}")
        if reg.name_en:
            print(f"            ({reg.name_en})")
    else:
        print("📋 اللائحة: غير محدد بدقة (راجع راكس للتحقق)")
    print()

    # Certification phrase + framing
    if cert.is_regulated:
        print(f"⚠️ هذا المنتج خاضع للتنظيم الإلزامي.")
    else:
        print(f"✅ خبر جيد يا {user_name}! هذا المنتج غير خاضع للتنظيم الإلزامي — متطلبات أبسط.")
    print()
    print(f"✓ متطلبات الشهادة (AR): {cert.phrase_ar}")
    print(f"✓ Certification (EN):  {cert.phrase_en}")
    print()

    # Standard caveat
    print("⚠️ تنبيه: قد تتغير رموز HS ومتطلباتها. تحقّق من المصادر الرسمية للاطلاع على المتطلبات المحدّثة.")
    print()

    # Official source link
    print(f"📌 عرض رمز HS في SABER: {detail.saber_link}")
    print()

    # PDF CTA — the conversion hook
    if detail.pdf_report_available:
        print("📄 احصل على التقرير الكامل (PDF) — مجاناً مقابل بريدك الإلكتروني.")
        print("   يشمل: المعايير المرجعية الكاملة، الدليل خطوة بخطوة، التكلفة المقدّرة،")
        print("   الزمن المتوقع، وقائمة المختبرات المعتمدة لدى راكس.")
    else:
        print("📄 ليس لدينا تقرير عميق لهذا الكود — تواصل مع راكس مباشرةً للحصول على المساعدة.")


def main() -> None:
    here = Path(__file__).resolve().parent
    data_dir = here.parent / "data"
    engine = SearchEngine(data_dir=data_dir)

    # Demo 1: Health check
    header("Demo 0 — engine stats")
    stats = engine.stats()
    for k, v in stats.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for k2, v2 in v.items():
                print(f"    {k2}: {v2}")
        else:
            print(f"  {k}: {v}")

    # Demo 1: Reproduce the Waleed flow — vague Arabic input
    user_name = "وليد"
    header(f"Demo 1 — vague Arabic query: 'أجهزة كهربائية' (Waleed-style disambiguation)")
    render_disambiguation(engine, "أجهزة كهربائية", user_name)

    # Demo 2: User picks an option from the menu → drill into details.
    # The sample conversation used HS 903033000000 (XDS data); in our master we
    # have HS 903040000001 (measuring instruments) as the equivalent.
    header("Demo 2 — user picks option, show detail (HS 903040000001 — measuring instruments)")
    render_detail(engine, "903040000001", user_name)

    # Demo 3: Tree-grouped disambiguation (our enhancement over XDS)
    header("Demo 3 — grouped disambiguation: 'بطارية' grouped by chapter")
    render_grouped_disambiguation(engine, "بطارية", user_name)

    # Demo 4: Numeric prefix search
    header("Demo 4 — numeric prefix: '8703' (motor vehicles)")
    for r in engine.search("8703", limit=5):
        print(f"  {r.hs_code} — {r.product_name_ar[:80]}")

    # Demo 5: Specific 12-digit code drill-down
    header("Demo 5 — specific code drill-down: 870380000001 (or whatever 8703 row exists)")
    sample = engine.search("8703", limit=1)
    if sample:
        render_detail(engine, sample[0].hs_code, user_name)

    # Demo 6: English keyword (we have some EN data in product_sub_type via regulations)
    header("Demo 6 — English keyword search: 'battery'")
    # Our data is mostly Arabic, but normalized substring still works for ascii
    en_results = engine.search("battery", limit=5)
    if en_results:
        for r in en_results:
            print(f"  {r.hs_code} — {r.product_name_ar[:60]}")
    else:
        print("  (no English matches in product names — our master data is mostly Arabic;")
        print("   add English product names later for EN-keyword search.)")

    # Demo 7: A non-regulated example — to verify the 'good news' framing
    header("Demo 7 — non-regulated code drill-down (Free-Trade)")
    nonreg_row = next(
        (r for r in engine._hs_codes if r.get("certification_key") == "supplier_declaration_free_trade"),
        None,
    )
    if nonreg_row:
        render_detail(engine, nonreg_row["hs_code"], user_name)


if __name__ == "__main__":
    main()
