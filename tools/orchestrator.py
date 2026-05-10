import os
import json
import logging
from typing import Optional
from dotenv import load_dotenv
from anthropic import Anthropic
from tools.xds_query import XDSQueryEngine

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

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
        self.MAX_HISTORY = 40  # Keep last 20 exchanges (40 messages)

    def process_message(self, user_message: str, chat_id: str) -> str:
        """
        Main entry point: add user message to history, run Claude with tools,
        manage tool use loop, return final response.
        """
        # Get or init history for this chat
        history = self.chat_histories.setdefault(chat_id, [])

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
                "description": "Search Saudi Arabia import compliance database for a product or HS code. Returns a list of matching HS codes with product names, regulation names, and detail page URLs.",
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
                "description": "Submit user's contact information to RACS CRM. Only call this after you have collected the user's name, email, and phone number.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "User's name"
                        },
                        "email": {
                            "type": "string",
                            "description": "User's email address"
                        },
                        "phone": {
                            "type": "string",
                            "description": "User's phone number"
                        }
                    },
                    "required": ["name", "email", "phone"]
                }
            }
        ]

        system_prompt = self._build_system_prompt()

        while True:
            # Call Claude
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=history,
                tools=tools
            )

            # Check stop reason
            if response.stop_reason == "end_turn":
                # Claude is done, extract text response
                text = None
                for block in response.content:
                    if hasattr(block, "text"):
                        text = block.text
                        break

                # Add assistant response to history
                history.append({"role": "assistant", "content": response.content})

                return text or "I'm having trouble with that. Please try again."

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

    def _execute_tool(self, tool_name: str, tool_input: dict, chat_id: str) -> str:
        """Execute a tool call and return JSON string result."""
        try:
            if tool_name == "search_xds":
                query = tool_input.get("query", "")
                print(f"[{chat_id}] Tool: search_xds('{query}')")
                results = XDSQueryEngine.search(query)
                if not results:
                    return json.dumps({"error": "No results found", "results": []}, ensure_ascii=False)
                return json.dumps(results, ensure_ascii=False)

            elif tool_name == "get_regulation_detail":
                url = tool_input.get("url", "")
                print(f"[{chat_id}] Tool: get_regulation_detail()")
                detail = XDSQueryEngine.get_detail(url)
                if not detail:
                    return json.dumps({"error": "Could not fetch regulation details"}, ensure_ascii=False)
                return json.dumps(detail, ensure_ascii=False)

            elif tool_name == "submit_lead":
                name = tool_input.get("name", "")
                email = tool_input.get("email", "")
                phone = tool_input.get("phone", "")
                print(f"[{chat_id}] Tool: submit_lead(name='{name}', email='{email}', phone='{phone}')")

                from bot.lead_capture import LeadCapture
                lc = LeadCapture()
                success = lc.submit_lead({
                    "name": name,
                    "email": email,
                    "phone": phone,
                    "chat_id": chat_id
                })
                if success:
                    return json.dumps({"success": True, "message": "Lead submitted successfully"}, ensure_ascii=False)
                else:
                    return json.dumps({"success": False, "message": "Lead submission failed"}, ensure_ascii=False)

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

2. **get_regulation_detail**: After the user picks a specific product (or if search returns only one product), call this tool with the detail_url to fetch the complete regulation page. This gives you all the compliance requirements, standards, product classifications, and other details needed for the response.

3. **submit_lead**: When the user wants to be contacted by a specialist, collect their name, email, and phone number conversationally (one per turn), then call this tool to submit the lead to the RACS CRM.

### Search Results & Options

When you call search_xds and get multiple results with different HS codes:
- Present them as numbered options: "I found these HS codes in our database:\nOption 1: **850440** — Chargers for video game consoles (2 matches)\nOption 2: **950450** — Video game consoles (3 matches)\n\nWhich one best describes your product?"
- Once the user picks, call get_regulation_detail with the chosen product's detail_url
- Present the full compliance requirements in RACS brand voice

### Conversation Flow

- **User describes a product**: Search with search_xds, present options if multiple, or fetch detail directly if one match
- **User provides an HS code**: Search with search_xds, then fetch detail
- **User pivots to a different product**: Just search again — don't get stuck. The user said "No I mean toys", so search for toys. Natural conversation, not state machines.
- **User wants contact**: Collect name → email → phone → submit_lead
- **Follow-up questions**: Use conversation history to answer questions about the product already discussed

### Critical Rules

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

4. **Conversational pivots**. If the user says "Actually, I want to import Y instead", just search for Y. No state machine logic, no "are you sure?" — just flow naturally.

5. **Lead capture is conversational**. Don't ask "name, email, phone" in a form. Ask naturally: "I'd love to connect you with a specialist. What's your name?" → user replies → "Great! And what's your email?" → etc. Only call submit_lead once you have all three.

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
Assistant: "I found these HS codes in our database:\nOption 1: **350790** — Enzymatic preparations (1 match)\nOption 2: **731021** — Fruit juice products (3 matches)\nOption 3: **843510** — Juicers (2 matches)\n\nWhich one matches what you're importing?"
User: "Option 2"
Assistant: [calls get_regulation_detail on Option 2's detail_url]
Assistant: [synthesizes regulations in RACS voice with one CTA]

### Flow 2: Product Pivot (Mid-Conversation)

User: "juice"
Assistant: [shows 3 options]
User: "No I mean toys"
Assistant: [calls search_xds for "toys"]
Assistant: "I found these toy-related codes:\nOption 1: **950450** — Toys and games (5 matches)..."

### Flow 3: Lead Capture

User: "Can someone from your team reach out?"
Assistant: "I'd love to connect you with a RACS specialist. What's your name?"
User: "Ali"
Assistant: "Great, Ali! What's your email address?"
User: "ali@example.com"
Assistant: "Perfect! And your phone number?"
User: "+966-55-123-4567"
Assistant: [calls submit_lead with name, email, phone]
Assistant: "✅ Thank you! A RACS specialist will reach out to you at ali@example.com..."

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
