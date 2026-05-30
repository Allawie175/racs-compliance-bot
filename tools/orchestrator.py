import os
import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from anthropic import Anthropic
from tools.conversation_logger import ConversationLogger

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

_engine_choice = os.getenv("HS_ENGINE", "local").strip().lower()
if _engine_choice == "xds":
    from tools.xds_query import XDSQueryEngine
else:
    from tools.local_xds_query import LocalXDSQueryEngine as XDSQueryEngine
logger.info(f"HS engine active: {_engine_choice} ({XDSQueryEngine.__module__}.{XDSQueryEngine.__name__})")

# Load brand voice and CTA strategy
BRAND_VOICE_PATH = "brand/racs_voice.md"
CTA_STRATEGY_PATH = "config/cta_strategy.json"

with open(BRAND_VOICE_PATH, "r") as f:
    BRAND_VOICE = f.read()

with open(CTA_STRATEGY_PATH, "r") as f:
    CTA_STRATEGY = json.load(f)


class Orchestrator:
    """RACS compliance assistant powered by Claude with tool use."""

    def __init__(self):
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore")
            try:
                self.client = Anthropic()
            except TypeError as e:
                if "proxies" in str(e):
                    import os
                    proxy_vars = {}
                    for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
                        if var in os.environ:
                            proxy_vars[var] = os.environ.pop(var)
                    try:
                        self.client = Anthropic()
                    finally:
                        for var, val in proxy_vars.items():
                            os.environ[var] = val
                else:
                    raise

        self.model = "claude-sonnet-4-6"
        self.chat_histories: dict[str, list] = {}  # Isolated per-chat history
        self.tools_used: dict[str, set] = {}  # Track tools used per chat
        self.MAX_HISTORY = 40  # Keep last 20 exchanges (40 messages)
        self.product_interests: dict[str, list[str]] = {}  # HS codes user viewed, per chat
        self._db = ConversationLogger()

    def process_message(self, user_message: str, chat_id: str) -> str:
        """
        Main entry point: add user message to history, run Claude with tools,
        manage tool use loop, return final response.
        """
        # Get or init history and tools for this chat
        history = self.chat_histories.setdefault(chat_id, [])
        self.tools_used.setdefault(chat_id, set())

        # Add user message
        history.append({"role": "user", "content": user_message})

        # Run Claude with tool use loop
        response_text = self._run_claude(history, chat_id)

        # Trim history if it gets too long
        if len(history) > self.MAX_HISTORY:
            self.chat_histories[chat_id] = history[-self.MAX_HISTORY:]

        return response_text

    def _run_claude(self, history: list, chat_id: str) -> str:
        """
        Main tool use loop: call Claude, handle tool calls, loop until end_turn.
        Claude reads full history and decides what to do.
        """
        tools = [
            {
                "name": "search_xds",
                "description": "Search Saudi Arabia import compliance database for a product or HS code. Returns a comprehensive list of all matching HS codes with product names, regulation names, and detail page URLs (automatically fetches all pages).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Product name or HS code to search for"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_regulation_detail",
                "description": "Fetch full regulation details for a specific product using its detail page URL from search_xds results. Call this after the user has confirmed which product they want details for.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Detail page URL from search_xds result"
                        }
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "submit_lead",
                "description": "Mark this lead as 'requested callback' in the RACS CRM. Only call this when the user explicitly asks to be contacted by a specialist (e.g., 'have someone call me', 'I'd like to talk to a specialist', 'can you reach out?'). The user's contact info is already saved from the initial form — you do not need to collect it again. This tool just signals the highest level of intent so Sales prioritizes outreach.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                "cache_control": {"type": "ephemeral"},
            }
        ]

        system_prompt = self._build_system_prompt()
        system_blocks = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        while True:
            # Call Claude
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_blocks,
                messages=history,
                tools=tools,
            )

            # Log cache stats so we can verify caching in Railway logs
            usage = getattr(response, "usage", None)
            if usage is not None:
                cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
                cr = getattr(usage, "cache_read_input_tokens", 0) or 0
                inp = getattr(usage, "input_tokens", 0) or 0
                out = getattr(usage, "output_tokens", 0) or 0
                print(f"[{chat_id}] usage in={inp} cache_w={cw} cache_r={cr} out={out}")

            # Check stop reason
            if response.stop_reason == "end_turn":
                # Concatenate all text blocks (Claude sometimes emits multiple)
                texts = [b.text for b in response.content if hasattr(b, "text") and b.text]
                text = "\n\n".join(t.strip() for t in texts if t.strip())

                history.append({"role": "assistant", "content": response.content})

                if text:
                    return text

                # No text returned. Pick a sensible default based on the last tool the bot ran.
                last_tool = self._last_tool_called(history)
                print(f"[{chat_id}] end_turn with no text. last_tool={last_tool}")
                if last_tool == "submit_lead":
                    return "✅ Done — a RACS specialist will reach out to you using the contact info you shared earlier. Expect a response within one business day."
                return "I'm having trouble with that. Please try again."

            elif response.stop_reason == "tool_use":
                # Claude wants to use a tool
                # Add assistant's message (with tool_use blocks) to history
                history.append({"role": "assistant", "content": response.content})

                # Execute all tool calls
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = self._execute_tool(block.name, block.input, chat_id)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result
                        })

                # Add tool results as a user turn and loop
                history.append({"role": "user", "content": tool_results})

            else:
                # Unexpected stop reason
                logger.warning(f"[{chat_id}] Unexpected stop_reason: {response.stop_reason}")
                history.append({"role": "assistant", "content": response.content})
                return "I encountered an unexpected condition. Please try again."

    @staticmethod
    def _last_tool_called(history: list) -> Optional[str]:
        """Walk history backwards and return the name of the most recent tool_use block."""
        for msg in reversed(history):
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in reversed(content):
                name = getattr(block, "name", None) if not isinstance(block, dict) else block.get("name")
                block_type = getattr(block, "type", None) if not isinstance(block, dict) else block.get("type")
                if block_type == "tool_use" and name:
                    return name
        return None

    @staticmethod
    def _extract_hs_code(url: str) -> Optional[str]:
        """Pull the hscode= query param out of an XDS detail URL."""
        try:
            q = parse_qs(urlparse(url).query)
            code = q.get("hscode", [None])[0]
            return code if code else None
        except Exception:
            return None

    def _execute_tool(self, tool_name: str, tool_input: dict, chat_id: str) -> str:
        """Execute a tool call and return JSON string result."""
        # Track tool usage
        self.tools_used[chat_id].add(tool_name)

        try:
            if tool_name == "search_xds":
                query = tool_input.get("query", "")
                print(f"[{chat_id}] Tool: search_xds('{query}')")

                # Fetch first 2 pages to balance completeness and cost
                all_results = []
                for current_page in range(1, 3):
                    page_results = XDSQueryEngine.search(query, page=current_page)
                    if not page_results:
                        break
                    all_results.extend(page_results)

                # Advance funnel stage: user searched
                self._db.advance_stage(chat_id, "searched")

                if not all_results:
                    return json.dumps({"error": "No results found", "results": []}, ensure_ascii=False)
                return json.dumps(all_results, ensure_ascii=False)

            elif tool_name == "get_regulation_detail":
                url = tool_input.get("url", "")
                print(f"[{chat_id}] Tool: get_regulation_detail()")
                detail = XDSQueryEngine.get_detail(url)

                # Advance funnel stage and record which HS code the user viewed
                hs_code = self._extract_hs_code(url)
                if hs_code:
                    interests = self.product_interests.setdefault(chat_id, [])
                    if hs_code not in interests:
                        interests.append(hs_code)
                    product_interest = ",".join(interests)
                else:
                    product_interest = None
                self._db.advance_stage(chat_id, "viewed_regulation", product_interest=product_interest)

                if not detail:
                    return json.dumps({"error": "Could not fetch regulation details"}, ensure_ascii=False)
                return json.dumps(detail, ensure_ascii=False)

            elif tool_name == "submit_lead":
                print(f"[{chat_id}] Tool: submit_lead (callback requested)")
                product_interest = ",".join(self.product_interests.get(chat_id, [])) or None
                ok = self._db.advance_stage(chat_id, "requested_callback", product_interest=product_interest)
                if ok:
                    return json.dumps({"success": True, "message": "Callback request flagged in CRM"}, ensure_ascii=False)
                return json.dumps({"success": False, "message": "Could not flag callback in CRM"}, ensure_ascii=False)

            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)

        except Exception as e:
            logger.error(f"[{chat_id}] Tool execution failed: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def _build_system_prompt(self) -> str:
        """Build the comprehensive system prompt for Claude."""
        return f"""{BRAND_VOICE}

---

## Your Role

You are the RACS Compliance Assistant, an expert on Saudi Arabia import regulations. Your job is to help importers understand what compliance steps are needed to import products.

---

## How to Operate

### Tool Use Guidance

You have access to three tools:

1. **search_xds**: Call this when the user describes a product or provides an HS code. The tool searches our compliance database and returns matching products with HS codes, regulation names, and detail page URLs.
   - **Search in the user's language first.** Our database is Arabic-primary — most product names are stored in Arabic. If the user wrote Arabic, pass the Arabic term. If they wrote English, pass the English term. Example: user says "ورق" → call `search_xds(query="ورق")`. User says "paper" → call `search_xds(query="paper")`.
   - **Fallback ONCE to the other language if the first call returns zero results.** Example: `search_xds(query="paper")` returns 0 hits → immediately retry with `search_xds(query="ورق")`. After that single fallback, stop and either present what you have or ask the user to clarify the product. Do not loop further.
   - **HS codes (digits) are language-agnostic** — pass them as-is on the first call, no fallback needed.

2. **get_regulation_detail**: After the user picks a specific product (or if search returns only one product), call this tool with the detail_url to fetch the complete regulation page. This gives you all the compliance requirements, standards, product classifications, and other details needed for the response.

3. **submit_lead**: When the user wants to be contacted by a specialist, collect their name, email, and phone number conversationally (one per turn), then call this tool to submit the lead to the RACS CRM.

### Search Results & Options

When you call search_xds and get multiple results with different HS codes:
- You receive ALL results across all pages automatically (pagination is handled internally)
- **Present EVERY SINGLE result as numbered options. Do NOT filter, prioritize, or limit the list.** Show all 10, 15, 20, or however many you received.
- Format: "I found these HS codes in our database:\nOption 1: **850440** — Chargers for video game consoles\nOption 2: **950450** — Video game consoles\nOption 3: ...\n\nWhich one best describes your product?"
- The user wants to see everything available, not your filtered selection
- Once the user picks, call get_regulation_detail with the chosen product's detail_url
- Present the full compliance requirements in RACS brand voice with all available information

### Presenting Regulation Details

When you receive regulation detail data from get_regulation_detail, present it with this structure:
1. **Regulation name** and **summary** (always include - this is the official description)
2. **Certification Requirements**, **Products Covered**, **Product Classification** (core compliance info)
3. **SABER Links — render ONLY the keys actually present in `saber_links`**:
   - `hs_code_page` → render as "View HS Code in SABER" with that URL
   - `saber_portal` → render as "SABER Portal" with that URL
   - `regulation_pdf` → ONLY render a "Read Full Technical Regulation (PDF)" link if THIS KEY IS LITERALLY PRESENT in the saber_links dict. If `regulation_pdf` is not in saber_links, DO NOT mention, render, or invent a PDF link of any kind. Never reuse `detail_url`, `hs_code_page`, or any other URL as a PDF link. Most regulations do not have a PDF — that is normal; just omit the line.
4. **Additional notes/disclaimers** as provided by XDS

**Never use the internal `detail_url` in user-facing text.** That field starts with `https://local.racs/` and is for internal tool routing only — it is not a clickable link, it is not a PDF, and showing it to the user breaks trust. The only user-facing URLs are the values inside `saber_links`.

Never omit the regulation summary or SABER links. Users want to understand WHAT the regulation is and WHERE to find official sources.

### Conversation Flow

- **User describes a product**: Search with search_xds, present options if multiple, or fetch detail directly if one match
- **User provides an HS code**: Search with search_xds, then fetch detail
- **User pivots to a different product**: Just search again — don't get stuck. The user said "No I mean toys", so search for toys. Natural conversation, not state machines.
- **User wants contact**: Their info was already captured by the form before chat started. Just call `submit_lead` (no arguments needed) to flag the callback request — do NOT re-collect name/email/phone.
- **Follow-up questions**: Use conversation history to answer questions about the product already discussed

### Critical Rules

0. **ALWAYS reply in the user's language.** Detect the language of the user's MOST RECENT message and write your entire reply in that language — every word, every label, every bullet, every CTA. If the user just wrote Arabic, your entire response must be Arabic. If they wrote English, English. If they switch mid-conversation, switch with them on your very next reply — do not stay anchored to the earlier language just because the conversation started in it. The initial welcome message defaults to English, but THE MOMENT the user writes in another language, switch immediately and stay there until they switch back. This is non-negotiable.

1. **NEVER mention XDS or the database by name**. Users believe this is RACS's own expertise. Say "I found these HS codes in our database" but never "XDS says..."

2. **ONLY present compliance information that comes from XDS**. NEVER invent or estimate:
   - ❌ Don't make up timeline estimates (8-14 weeks, 2-3 months, etc.) unless XDS explicitly states them
   - ❌ Don't invent cost estimates ($5,000, $10K-15K, etc.) unless XDS explicitly states them
   - ❌ Don't describe procedural steps (1. Submit documents, 2. Testing, 3. Issuance) unless XDS explicitly lists them
   - ❌ Don't add pain points or contextual notes not in XDS data
   - ✅ DO present everything XDS provides: Products Covered, Certification Requirements, Product Classification, Standards, actual Timelines/Costs when listed
   - ✅ If XDS doesn't have a timeline or cost, say: "XDS doesn't specify the timeline/cost for this regulation. Let me connect you with a specialist for an accurate estimate."

3. **Handle ambiguity gracefully**. If search returns multiple distinct products:
   - List them as numbered options with HS codes
   - Wait for user to pick
   - Fetch detail for the chosen product
   - Never auto-select or guess
   - **Match the user's language for option labels**: when responding in Arabic, write "الخيار 1:" / "الخيار 2:" — NOT "Option 1:" / "Option 2:". When responding in English, use "Option 1:" / "Option 2:". Consistency matters for trust.

4. **Conversational pivots**. If the user says "Actually, I want to import Y instead", just search for Y. No state machine logic, no "are you sure?" — just flow naturally.

5. **Do NOT collect name/email/phone in chat.** The user already filled a form before the chat opened — their contact info is on file. When the user asks to be contacted by a specialist, simply confirm warmly (e.g., "Got it, I'll have a specialist reach out to you at the email you shared.") and call `submit_lead` to flag the callback request. Asking for info again makes the user feel the bot wasn't paying attention.

6. **Format matters**. Use the RACS brand voice structure:
   - Emoji header (e.g., 🛴 for product)
   - One-line summary
   - Structured requirements with ✓ bullets
   - **ONLY timeline/costs if XDS provides them** (otherwise skip or offer specialist consultation)
   - Exactly ONE call-to-action at the end

7. **Include exactly one CTA per response**. Pick from the brand voice CTA pools based on product complexity, timeline pressure, budget concerns, etc.

8. **Be honest**. If you don't have enough information, say so. If compliance is complex, acknowledge it. Offer specialist consultation when needed rather than guessing.

---

## Example Flows

### Flow 1: Direct Product Search → Multiple Options → Detail

User: "juice"
Assistant: "I found these HS codes in our database:\nOption 1: **350790** — Enzymatic preparations\nOption 2: **731021** — Fruit juice products\nOption 3: **843510** — Juicers\n\nWhich one matches what you're importing?"
User: "Option 2"
Assistant: [calls get_regulation_detail on Option 2's detail_url]
Assistant: "📋 **Fruit Juice Products**\n\n**Regulation:** [regulation_name from XDS]\n\n**About this Regulation:** [regulation_summary - the official description]\n\n**Products Covered:**\n✓ [List from products_covered]\n\n**Certification Requirements:**\n✓ [List from certification_requirements]\n\n**Product Classification:**\n⚠️ [Type from product_classification]\n\n**📌 Official Resources:**\n- 📄 [Read Full Technical Regulation](regulation_pdf link if available)\n- 🔗 [View HS Code in SABER](hs_code_page link)\n- 🌐 [SABER Portal](saber_portal link)\n\n[One CTA from RACS voice pools]"

### Flow 2: Product Pivot (Mid-Conversation)

User: "juice"
Assistant: [shows 3 options]
User: "No I mean toys"
Assistant: [calls search_xds for "toys"]
Assistant: "I found these toy-related codes:\nOption 1: **950450** — Toys and games (5 matches)..."

### Flow 3: Callback Request (contact info already on file)

User: "Can someone from your team reach out?"
Assistant: [calls submit_lead — no arguments]
Assistant: "✅ Done — a RACS specialist will reach out to you at the email and phone you shared earlier. Expect contact within one business day. Anything else I can help with in the meantime?"

---

## Tone Reminders

- Professional but conversational (not corporate stiff)
- Trustworthy and transparent
- Practical (actionable next steps)
- Helpful first, sales second
- Respectful of user's time
"""

    def process_query(self, user_message: str, chat_id: str, turn_count=1) -> str:
        """Backward compatibility method."""
        return self.process_message(user_message, chat_id)


if __name__ == "__main__":
    # Quick test
    orchestrator = Orchestrator()
    response = orchestrator.process_message(
        user_message="Hi, I want to import some juice.",
        chat_id="test_chat"
    )
    print(response)
