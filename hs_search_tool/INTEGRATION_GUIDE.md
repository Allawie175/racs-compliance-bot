# Integration Guide

How to wire `hs_search_tool` into a chatbot, REST API, or any agent.

---

## 1. Drop the package into your project

Move the entire `hs_search_tool/` folder into your project root. Your project layout becomes:

```
your_bot_project/
├── hs_search_tool/      ← drop the whole folder here
│   ├── __init__.py
│   ├── search.py
│   ├── data/
│   └── ...
├── your_bot.py
└── ...
```

Install runtime deps (note: the search engine itself has no third-party deps; pandas is only needed if you re-run `prepare_data.py`):

```bash
py -3 -m pip install pytest
# pandas only if you'll regenerate data tables
```

Test the install:

```bash
py -3 -m pytest hs_search_tool/tests/ -v
# expected: 42 passed
```

---

## 2. The minimum viable bot wiring

```python
# your_bot.py
from hs_search_tool import SearchEngine

# Instantiate once, at startup. Loads ~1.4 MB into memory.
engine = SearchEngine(data_dir="hs_search_tool/data")


def handle_user_message(text: str, user_name: str) -> str:
    """Convert a user message into a bot response."""

    # Step 1: route the query
    if text.isdigit():
        results = engine.search(text, limit=10)
    else:
        results = engine.search(text, limit=10)

    if not results:
        return f"عذراً يا {user_name}، لم أجد نتائج. حاول كلمات مختلفة أو رمز HS."

    # Step 2: if many results, show disambiguation menu
    if len(results) > 1:
        lines = [f"وجدت {len(results)} نتائج يا {user_name}، أي منها يصف منتجك؟\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.hs_code} — {r.product_name_ar[:80]}")
        return "\n".join(lines)

    # Step 3: single result → drill into detail
    detail = engine.get_details(results[0].hs_code)
    return render_detail(detail, user_name)


def render_detail(detail, user_name: str) -> str:
    """Format a ProductDetail into the standard structured response."""
    cert = detail.certification
    blocks = []

    blocks.append(f"📏 {detail.product_name_ar}")
    blocks.append(f"HS: {detail.hs_code}\n")

    # Hierarchy
    blocks.append(f"   ▸ {detail.parent_4} — {detail.parent_4_description or '(غير متوفر)'}")
    blocks.append(f"      ▸ {detail.parent_6} — {detail.parent_6_description or '(غير متوفر)'}\n")

    # Regulation
    if detail.regulation:
        blocks.append(f"📋 اللائحة: {detail.regulation.name_ar}")
        if detail.regulation.name_en:
            blocks.append(f"            ({detail.regulation.name_en})\n")

    # Certification — frame as good news for non-regulated
    if cert.is_regulated:
        blocks.append(f"⚠️ خاضع للتنظيم الإلزامي.")
    else:
        blocks.append(f"✅ خبر جيد يا {user_name}! غير خاضع للتنظيم — متطلبات أبسط.")

    blocks.append(f"✓ {cert.phrase_ar}")
    blocks.append(f"  ({cert.phrase_en})\n")

    # Official link
    blocks.append(f"📌 SABER: {detail.saber_link}\n")

    # PDF CTA — the conversion hook
    if detail.pdf_report_available:
        blocks.append(
            "📄 احصل على التقرير الكامل (PDF) — مجاناً مقابل بريدك الإلكتروني. "
            "يشمل المعايير المرجعية، التكلفة، الزمن، والمختبرات المعتمدة."
        )

    return "\n".join(blocks)
```

---

## 3. Pattern: Claude as orchestrator on top

The search engine is deterministic. Use Claude (or any LLM) to:

1. **Understand intent**: "Is this a code lookup, a vague keyword, or a follow-up to the previous turn?"
2. **Translate the query** if user wrote English but our data is mostly Arabic
3. **Pick from disambiguation menu** if the user reply is ambiguous ("the third one", "scooter not motorcycle")
4. **Wrap structured data in natural language**

```python
import anthropic
from hs_search_tool import SearchEngine

engine = SearchEngine(data_dir="hs_search_tool/data")
claude = anthropic.Anthropic()

def orchestrate(user_text: str, history: list[dict]) -> str:
    # 1. Ask Claude what to search for
    plan = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=history + [{
            "role": "user",
            "content": f"""User said: {user_text!r}

Given prior conversation, decide:
  - search_query: what to look up in the HS database (Arabic or numeric)
  - intent: "search" | "drill_down" | "follow_up" | "small_talk"
  - selected_index: if user picked from a menu, which number (1-10)

Respond as JSON only.""",
        }],
    )
    plan_json = json.loads(plan.content[0].text)

    # 2. Execute the deterministic search
    if plan_json["intent"] == "drill_down" and plan_json.get("selected_index"):
        last_results = history[-1]["search_results"]  # cache prior results in history
        detail = engine.get_details(last_results[plan_json["selected_index"] - 1])
        facts = detail.to_dict()
    else:
        results = engine.search(plan_json["search_query"], limit=10)
        facts = [r.to_dict() for r in results]

    # 3. Ask Claude to render the response
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=RACS_SYSTEM_PROMPT,
        messages=history + [{
            "role": "user",
            "content": user_text,
        }, {
            "role": "assistant",
            "content": f"Database facts (use these — do NOT invent any data):\n{json.dumps(facts, ensure_ascii=False)}",
        }],
    )
    return response.content[0].text
```

The critical rule for the system prompt: **the LLM may only use facts from the search engine output. Never invent costs, timelines, standards, or procedures.**

---

## 4. Pattern: Tiered response (chat free → PDF premium)

The search engine already exposes `pdf_report_available` on each `ProductDetail`. Use this to drive the conversion CTA:

```python
def chat_response(detail) -> str:
    text = render_short_summary(detail)
    if detail.pdf_report_available:
        text += "\n\n📄 الحصول على التقرير الكامل (PDF) — مجاناً مقابل بريدك الإلكتروني."
    return text


def handle_user_email(email: str, last_hs_code: str):
    """When user shares email, generate and email the PDF report."""
    detail = engine.get_details(last_hs_code)
    # Call the parent project's PDF generator
    pdf_path = generate_pdf_report(
        hs_code=detail.hs_code,
        regulation=detail.regulation,
        # Pull deeper data from the parent project's master sheets
        standards=load_standards_for_code(detail.hs_code),
        approved_bodies=load_approved_bodies_for_regulation(detail.regulation.regulation_id),
    )
    send_email(email, pdf_path)
    save_lead_to_crm(email, last_hs_code, detail.regulation.regulation_id)
```

---

## 5. Data serialization for storage / APIs

Every result is JSON-serializable via `.to_dict()`:

```python
import json

detail = engine.get_details("903040000001")
payload = detail.to_dict()
print(json.dumps(payload, ensure_ascii=False, indent=2))
```

Use this for:
- REST API responses
- Conversation history persistence
- Caching layers (Redis, etc.)
- Webhook payloads

---

## 6. Things you must do in the consuming project

This package intentionally does NOT handle:

- **Personalization**: pull `user.first_name` from Telegram and inject into responses
- **Conversation memory**: store recent search results so "the third one" works as a follow-up
- **Rate limiting / abuse prevention**
- **Logging / analytics**: log every query → result mapping for tuning
- **The CTA delivery**: collect email, generate PDF, fire to CRM
- **English-keyword search**: our master data is mostly Arabic; if you need English keyword search, translate the query to Arabic before calling `engine.search()`

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `FileNotFoundError: Data directory not found` | Wrong `data_dir` path | Pass absolute path or `Path(__file__).parent / "hs_search_tool/data"` |
| Search returns 0 for known product | Singular/plural Arabic morphology | Try the alternate form; or have Claude rephrase |
| Parent description looks wrong | Derived-from-children quirk | Document in chat copy: "verify with SABER official link" |
| English keyword returns 0 | Master data is mostly Arabic | Translate query EN→AR before searching |
| `regulation_id` is `None` on a result | 2.4% of codes don't match a regulation | Show "regulation lookup unclear — contact RACs" |

---

## 8. Performance characteristics

- **Cold start**: ~50 ms (CSV load + index build)
- **Numeric prefix search**: O(n) over 5K rows ≈ 1–2 ms
- **Keyword search**: O(n) substring scan ≈ 5–10 ms
- **Drill-down (get_details)**: O(1) dict lookup ≈ 0.1 ms
- **Memory footprint**: ~3–5 MB resident
- **Concurrency**: safe — engine state is read-only after init

For higher scale (>100 QPS), wrap in async handlers; the engine itself is thread-safe.
