import os
import json
import random
import logging
from typing import Optional
from dotenv import load_dotenv
from anthropic import Anthropic
from tools.xds_query import XDSQueryEngine

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load brand voice and CTA strategy
BRAND_VOICE_PATH = "brand/racs_voice.md"
CTA_STRATEGY_PATH = "config/cta_strategy.json"

# Load brand voice guidelines
with open(BRAND_VOICE_PATH, "r") as f:
    BRAND_VOICE = f.read()

# Load CTA strategy
with open(CTA_STRATEGY_PATH, "r") as f:
    CTA_STRATEGY = json.load(f)


class Orchestrator:
    """
    RACs compliance intelligence engine.
    Intent-driven chatbot that feels like talking to a human consultant.
    """

    def __init__(self):
        import warnings
        # Suppress warnings during Anthropic client initialization
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore")
            try:
                self.client = Anthropic()
            except TypeError as e:
                if "proxies" in str(e):
                    # Work around Anthropic SDK proxy detection issue
                    import os
                    # Temporarily disable proxy environment variables
                    proxy_vars = {}
                    for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
                        if var in os.environ:
                            proxy_vars[var] = os.environ.pop(var)
                    try:
                        self.client = Anthropic()
                    finally:
                        # Restore proxy environment variables
                        for var, val in proxy_vars.items():
                            os.environ[var] = val
                else:
                    raise
        self.model = "claude-sonnet-4-6"
        # Per-chat state: richer than just history
        self.chat_state: dict[str, dict] = {}

    def _init_chat_state(self, chat_id: str):
        """Initialize per-chat state."""
        if chat_id not in self.chat_state:
            self.chat_state[chat_id] = {
                "history": [],            # last 6 turns [{role, content}]
                "turn_count": 0,
                "mode": "idle",           # idle | discovery | lead_capture
                "discovery": {
                    "product_description": "",
                    "clarifications": [],         # [{"question": ..., "answer": ...}]
                    "clarification_count": 0,
                    "proposed_hs_codes": [],      # [{"hs_code": ..., "product_name": ..., "reason": ...}]
                    "chosen_hs_code": None,       # 6-digit code chosen by user
                    "sub_code_options": [],       # XDS search results for chosen_hs_code variants
                    "sub_code_question": None,    # Claude-generated narrowing question
                    "chosen_sub_code": None       # final 10-digit code selected
                },
                "lead": {
                    "awaiting": None,             # "name" | "email" | "phone" | None
                    "name": None,
                    "email": None,
                    "phone": None,
                    "product_interest": ""
                }
            }

    def process_message(self, user_message: str, chat_id: str) -> str:
        """
        Central dispatcher: routes based on active mode or detected intent.
        The bot feels like one continuous conversation.
        """
        self._init_chat_state(chat_id)
        state = self.chat_state[chat_id]
        state["turn_count"] += 1

        print(f"[DEBUG] [{chat_id}] Turn {state['turn_count']} | Mode: {state['mode']}")

        # Rule 1: If in lead capture mode, collect fields (bypass intent detection)
        if state["mode"] == "lead_capture":
            response = self._handle_lead_step(user_message, chat_id)
            self._update_history(chat_id, user_message, response)
            return response

        # Rule 2: If in discovery mode, handle sub-states (bypass intent detection)
        if state["mode"] == "discovery":
            disco = state["discovery"]

            # Check if user is starting a NEW discovery request (reset and restart)
            if self._is_new_discovery_request(user_message):
                state["discovery"] = {
                    "product_description": "",
                    "clarifications": [],
                    "clarification_count": 0,
                    "proposed_hs_codes": [],
                    "chosen_hs_code": None,
                    "sub_code_options": [],
                    "sub_code_question": None,
                    "chosen_sub_code": None
                }
                response = self._handle_discovery_start(user_message, chat_id)
                self._update_history(chat_id, user_message, response)
                return response

            # Check in this order:
            # 1. If user picked a code and is waiting to narrow down sub-code, handle sub-code choice
            # 2. If we have proposals and user hasn't picked yet, handle their choice
            # 3. Otherwise, gather clarifications (auto-generates proposals when we have 2)
            if disco.get("chosen_hs_code") and disco.get("sub_code_question") and not disco.get("chosen_sub_code"):
                # Sub-state: user is answering the sub-code clarification question
                response = self._handle_sub_code_choice(user_message, chat_id)
            elif disco["proposed_hs_codes"] and not disco["chosen_hs_code"]:
                # Sub-state: user is picking an HS code
                response = self._handle_discovery_choice(user_message, chat_id)
            else:
                # Sub-state: gathering clarifications (or generating proposals)
                response = self._handle_discovery_clarification(user_message, chat_id)
            self._update_history(chat_id, user_message, response)
            return response

        # Rule 3: Detect intent and route
        intent_data = self._detect_intent(user_message, chat_id)
        print(f"[DEBUG] [{chat_id}] Detected intent: {intent_data['intent']} (confidence: {intent_data['confidence']})")

        intent = intent_data["intent"]
        confidence = intent_data["confidence"]

        if confidence == "low":
            response = "Could you tell me a bit more about what you're trying to import or what you need help with?"
        elif intent == "greeting":
            response = self._handle_greeting()
        elif intent == "contact_info":
            response = self._handle_contact_info()
        elif intent == "lead_capture":
            response = self._start_lead_capture(chat_id)
        elif intent == "discovery":
            response = self._handle_discovery_start(user_message, chat_id)
        elif intent == "direct_lookup":
            extracted_term = intent_data.get("extracted") or user_message.strip()
            response = self._handle_direct_lookup(extracted_term, user_message, chat_id)
        elif intent == "followup":
            response = self._handle_followup(user_message, chat_id)
        else:
            response = "I'm not sure I understand. Could you clarify?"

        self._update_history(chat_id, user_message, response)
        return response

    def _detect_intent(self, user_message: str, chat_id: str) -> dict:
        """
        Lightweight Claude call to classify intent.
        Returns: {"intent": "...", "confidence": "high|medium|low", "extracted": "..."}
        """
        state = self.chat_state[chat_id]
        history_context = json.dumps(state["history"][-2:], ensure_ascii=False) if state["history"] else "New conversation"

        system_prompt = """You are a routing classifier for a compliance assistant. Classify the user's message into exactly one intent.

INTENTS:
- "discovery": User describes a product but does not provide an HS code. They need help finding the right code.
- "direct_lookup": User provides an HS code (numeric) OR a specific product name ready for immediate compliance lookup.
- "followup": User is continuing a previous compliance topic (asks about timeline, costs, documents, clarification).
- "lead_capture": User wants to be contacted, speak to someone, or connect with a specialist. Phrases: "connect me", "call me", "speak to someone", "contact me", "reach out".
- "contact_info": User wants RACs phone/email/address.
- "greeting": User says hi, hello, or starts fresh.

Context (previous turns):
{history_context}

Respond with ONLY a JSON object, no other text:
{{"intent": "<one of above>", "confidence": "high|medium|low", "extracted": "<HS code, product name, or null>"}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=80,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )
            intent_text = response.content[0].text.strip()
            intent_data = json.loads(intent_text)
            return intent_data
        except (json.JSONDecodeError, IndexError, Exception) as e:
            print(f"[DEBUG] [{chat_id}] Intent detection failed: {e}")
            # Fall back to low confidence
            return {"intent": "unknown", "confidence": "low", "extracted": None}

    def _handle_greeting(self) -> str:
        """Warm welcome explaining bot capabilities."""
        return """👋 Welcome to RACs Compliance Assistant!

I'm here to help you understand what's needed to import products into Saudi Arabia.

You can:
✓ **Describe a product** and I'll help you find the right HS code
✓ **Provide an HS code** and I'll look up the regulations
✓ **Ask follow-up questions** about compliance requirements
✓ **Connect with a specialist** if you need detailed guidance

What are you importing, or how can I help?"""

    def _handle_contact_info(self) -> str:
        """Return RACs contact information."""
        phone = os.getenv("RACS_CONTACT_PHONE", "+966-XX-XXXX-XXXX")
        email = os.getenv("RACS_CONTACT_EMAIL", "compliance@racs.example")
        calendly = os.getenv("RACS_CALENDLY_LINK", "https://calendly.com/racs")

        return f"""📞 **RACs Contact Information**

📱 Phone: {phone}
✉️ Email: {email}
📅 Schedule a consultation: {calendly}

Ready to discuss your import requirements?"""

    def _start_lead_capture(self, chat_id: str) -> str:
        """Enter lead capture mode: ask for name."""
        state = self.chat_state[chat_id]
        state["mode"] = "lead_capture"
        state["lead"]["awaiting"] = "name"
        return "I'd love to connect you with a RACs specialist. What's your name?"

    def _handle_lead_step(self, user_message: str, chat_id: str) -> str:
        """Handle sequential lead capture steps."""
        state = self.chat_state[chat_id]
        lead = state["lead"]

        if lead["awaiting"] == "name":
            lead["name"] = user_message.strip()
            lead["awaiting"] = "email"
            return f"Thanks, {lead['name']}! What's your email address?"

        elif lead["awaiting"] == "email":
            lead["email"] = user_message.strip()
            lead["awaiting"] = "phone"
            return "And your phone number?"

        elif lead["awaiting"] == "phone":
            lead["phone"] = user_message.strip()
            lead["awaiting"] = None

            # Extract product interest from recent history
            for msg in reversed(state["history"]):
                if msg.get("role") == "assistant":
                    # Look for product mentions
                    if any(word in msg.get("content", "").lower() for word in ["hs code", "product", "import"]):
                        lead["product_interest"] = msg["content"][:200]
                        break

            # Submit to Airtable
            from bot.lead_capture import LeadCapture
            try:
                lead_capture_service = LeadCapture()
                lead_capture_service.submit_lead({
                    "name": lead["name"],
                    "email": lead["email"],
                    "phone": lead["phone"],
                    "product_interest": lead["product_interest"],
                    "chat_id": chat_id
                })
                state["mode"] = "idle"
                return f"""✅ Thank you, {lead['name']}!

A RACs specialist will reach out to you at {lead['email']} or {lead['phone']} within 24 hours.

Looking forward to helping you navigate Saudi Arabia's import requirements."""
            except Exception as e:
                print(f"[ERROR] [{chat_id}] Lead capture failed: {e}")
                state["mode"] = "idle"
                return f"""✅ Thank you, {lead['name']}!

We've noted your interest. A RACs specialist will reach out soon."""

    def _handle_discovery_start(self, user_message: str, chat_id: str) -> str:
        """User describes a product without an HS code. Start discovery mode."""
        state = self.chat_state[chat_id]
        state["mode"] = "discovery"
        disco = state["discovery"]
        disco["product_description"] = user_message
        disco["clarification_count"] = 0
        disco["clarifications"] = []

        # NEW: Extract product keyword and search XDS immediately
        keyword = self._extract_product_keyword(user_message)

        if keyword:
            xds_results = XDSQueryEngine.search(keyword)
            if xds_results:
                grouped = self._group_results_by_hs_prefix(xds_results)
                disco["proposed_hs_codes"] = grouped
                return self._format_xds_options(grouped)

        # Fallback: Ask clarifying questions if XDS search returns nothing
        return self._ask_discovery_clarification(user_message, chat_id)

    def _ask_discovery_clarification(self, product_description: str, chat_id: str) -> str:
        """Ask a clarifying question about the product."""
        state = self.chat_state[chat_id]
        disco = state["discovery"]

        # Format previous Q&As for context
        previous_qa = ""
        if disco["clarifications"]:
            previous_qa = "\nPrevious Q&A:\n" + "\n".join(
                [f"Q: {c.get('question', 'N/A')}\nA: {c.get('answer', 'N/A')}"
                 for c in disco["clarifications"]]
            )

        system_prompt = f"""You are a Saudi Arabia import specialist helping identify the correct HS code for a product.

The user is trying to find the right HS code for importing a product. Ask ONE focused clarifying question that would help narrow down the correct code.

Important unknowns to explore: material composition, power source, primary function, intended use, capacity/size, brand/type.

Product: {product_description}{previous_qa}

Ask the most important remaining question. Be conversational and natural. One question only. No preamble."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=150,
                system=system_prompt,
                messages=[{"role": "user", "content": f"I want to import: {product_description}"}]
            )
            question = response.content[0].text.strip()
            return question
        except Exception as e:
            print(f"[ERROR] [{chat_id}] Clarification generation failed: {e}")
            return "Could you tell me more about this product — what material is it made from, or what's its main function?"

    def _handle_discovery_clarification(self, user_message: str, chat_id: str) -> str:
        """User answered a clarification. Store it and ask next, or move to proposals."""
        state = self.chat_state[chat_id]
        disco = state["discovery"]

        # If this is not the first answer, append to the last stored question
        if disco["clarifications"] and "answer" not in disco["clarifications"][-1]:
            disco["clarifications"][-1]["answer"] = user_message
        else:
            # First answer - just store it for now, will add question context
            if not disco["clarifications"]:
                disco["clarifications"].append({"answer": user_message})
            else:
                # We have previous Q&A, this is a new answer after a new question
                disco["clarifications"].append({"answer": user_message})

        # Check if we have 2 answers yet
        if len(disco["clarifications"]) < 2:
            # Ask next clarification
            return self._ask_discovery_clarification(disco["product_description"], chat_id)
        else:
            # We have 2 answers, propose HS codes
            return self._propose_hs_codes(chat_id)

    def _propose_hs_codes(self, chat_id: str) -> str:
        """Generate 2-3 HS code candidates based on product description + clarifications."""
        state = self.chat_state[chat_id]
        disco = state["discovery"]

        # Build clarifications context from answers
        clarifications_text = "User answered:\n"
        for i, c in enumerate(disco["clarifications"], 1):
            answer = c.get('answer', 'N/A')
            clarifications_text += f"{i}. {answer}\n"

        system_prompt = f"""You are a Saudi Arabia HS code expert. Based on a product description and clarifications, propose 2-3 plausible HS code candidates.

Product: {disco['product_description']}

{clarifications_text}

For each candidate provide:
- hs_code: the 6-digit HS code (e.g., "850431")
- product_name: official product name for that code
- reason: one sentence why this code could fit

Propose only codes that are plausible. If you are certain of only one, propose it plus 1-2 adjacent codes commonly confused with it.

CRITICAL: Respond with ONLY a valid JSON object. No markdown, no explanation, no code blocks. Just raw JSON:
{{"candidates": [{{"hs_code": "850510", "product_name": "Lead-acid storage batteries", "reason": "Car batteries are classified as lead-acid automotive batteries"}}]}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                system=system_prompt,
                messages=[{"role": "user", "content": "Generate HS code candidates."}]
            )
            candidates_text = response.content[0].text.strip()
            print(f"[DEBUG] [{chat_id}] Claude response for HS codes: {candidates_text[:200]}")

            if not candidates_text:
                print(f"[ERROR] [{chat_id}] Claude returned empty response")
                return "I'm having trouble narrowing down the exact code. Let me connect you with a specialist to confirm. Sound good?"

            candidates_data = json.loads(candidates_text)
            disco["proposed_hs_codes"] = candidates_data.get("candidates", [])

            if not disco["proposed_hs_codes"]:
                print(f"[ERROR] [{chat_id}] No candidates in Claude response")
                return "I'm having trouble narrowing down the exact code. Let me connect you with a specialist to confirm. Sound good?"

            # Format as user-friendly message
            msg = "Based on what you've told me, here are the likely HS codes:\n\n"
            for i, cand in enumerate(disco["proposed_hs_codes"], 1):
                msg += f"**Option {i}: {cand['hs_code']}**\n"
                msg += f"Product: {cand['product_name']}\n"
                msg += f"Why: {cand['reason']}\n\n"

            msg += "Which one sounds right to you? (Just reply with the option number or the HS code)"
            return msg
        except json.JSONDecodeError as e:
            print(f"[ERROR] [{chat_id}] JSON parse failed: {e}")
            print(f"[ERROR] [{chat_id}] Raw response was: {candidates_text[:500] if 'candidates_text' in locals() else 'N/A'}")
            return "I'm having trouble narrowing down the exact code. Let me connect you with a specialist to confirm. Sound good?"
        except Exception as e:
            print(f"[ERROR] [{chat_id}] HS code proposal failed: {e}")
            import traceback
            traceback.print_exc()
            return "I'm having trouble narrowing down the exact code. Let me connect you with a specialist to confirm. Sound good?"

    def _handle_discovery_choice(self, user_message: str, chat_id: str) -> str:
        """User picked an HS code. Search XDS for variants and ask sub-code clarification if needed."""
        state = self.chat_state[chat_id]
        disco = state["discovery"]

        # Try to match user's choice to a candidate
        chosen_code = None
        user_lower = user_message.lower().strip()

        # First, try to match by option number (e.g., "Option 1", "option 1", "1")
        for i, cand in enumerate(disco["proposed_hs_codes"], 1):
            code = cand.get("hs_code", "")
            # Check for exact option number match: "option 1", "option 1:", "1.", " 1 ", etc.
            if f"option {i}" in user_lower or f"{i}" in user_lower.split():
                chosen_code = code
                print(f"[DEBUG] [{chat_id}] Matched option {i} -> {code}")
                break

        # If no match by option number, try to match by code itself
        if not chosen_code:
            for i, cand in enumerate(disco["proposed_hs_codes"], 1):
                code = cand.get("hs_code", "")
                if code and code in user_message:
                    chosen_code = code
                    print(f"[DEBUG] [{chat_id}] Matched code {code}")
                    break

        if not chosen_code:
            print(f"[DEBUG] [{chat_id}] No match found for: '{user_message}'. Proposed codes: {[c.get('hs_code', '') for c in disco['proposed_hs_codes']]}")
            return "I'm not sure which code you meant. Could you confirm the code number or option number?"

        disco["chosen_hs_code"] = chosen_code

        # Search XDS for variants of this code
        print(f"[DEBUG] [{chat_id}] Searching XDS for variants of {chosen_code}")
        xds_results = XDSQueryEngine.search(chosen_code)
        disco["sub_code_options"] = xds_results
        print(f"[DEBUG] [{chat_id}] Found {len(xds_results)} XDS variants")

        # If only 1 result or no results, skip sub-code question and go directly to detail
        if len(xds_results) <= 1:
            print(f"[DEBUG] [{chat_id}] Only 1 or 0 variants, skipping sub-code clarification")
            state["mode"] = "idle"
            return self._handle_direct_lookup(chosen_code, f"I want to import products with HS code {chosen_code}", chat_id)

        # Multiple variants found, ask a clarifying question
        print(f"[DEBUG] [{chat_id}] Multiple variants found, asking sub-code clarification")
        return self._ask_sub_code_clarification(chat_id)

    def _ask_sub_code_clarification(self, chat_id: str) -> str:
        """Claude generates a smart clarification question to narrow down the sub-code."""
        state = self.chat_state[chat_id]
        disco = state["discovery"]

        # Build context about the variants
        variants_text = "\n".join([
            f"- {r.get('hs_code', '')}: {r.get('product_name', '')} ({r.get('regulation', '')})"
            for r in disco["sub_code_options"]
        ])

        # Build context about clarifications so far
        clarifications_text = "\n".join([
            f"Q: {c.get('question', 'N/A')}\nA: {c.get('answer', '')}"
            for c in disco["clarifications"]
        ])

        print(f"[DEBUG] [{chat_id}] Generating sub-code clarification question")
        print(f"[DEBUG] [{chat_id}] Product: {disco['product_description']}")
        print(f"[DEBUG] [{chat_id}] Variants found: {len(disco['sub_code_options'])}")

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=120,
                timeout=15.0,  # 15 second timeout to prevent hanging
                messages=[{
                    "role": "user",
                    "content": f"""User wants to import: {disco['product_description']}

Prior clarifications:
{clarifications_text}

HS code {disco['chosen_hs_code']} has these variants in XDS:
{variants_text}

Generate ONE short clarifying question to determine which variant matches the user's product.
Return ONLY the question text, no preamble."""
                }]
            )

            question = response.content[0].text.strip()
            disco["sub_code_question"] = question
            print(f"[DEBUG] [{chat_id}] Generated question: {question}")
            return question

        except Exception as e:
            print(f"[ERROR] [{chat_id}] Sub-code clarification generation failed: {e}")
            import traceback
            traceback.print_exc()
            # Fall back to simple question
            state["mode"] = "idle"
            return self._handle_direct_lookup(disco["chosen_hs_code"], f"HS code {disco['chosen_hs_code']}", chat_id)

    def _handle_sub_code_choice(self, user_message: str, chat_id: str) -> str:
        """User answered the sub-code clarification question. Match to best variant and proceed to detail."""
        state = self.chat_state[chat_id]
        disco = state["discovery"]

        # Build list of variants for Claude to match
        variants_text = "\n".join([
            f"- {r.get('hs_code', '')}: {r.get('product_name', '')}"
            for r in disco["sub_code_options"]
        ])

        print(f"[DEBUG] [{chat_id}] Matching user answer to sub-code variant")

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=80,
                timeout=15.0,  # 15 second timeout to prevent hanging
                messages=[{
                    "role": "user",
                    "content": f"""Question asked: {disco['sub_code_question']}
User answered: {user_message}

Available variants:
{variants_text}

Return ONLY the HS code of the best matching variant (e.g., "871160900000"). No other text."""
                }]
            )

            chosen_sub_code = response.content[0].text.strip()
            print(f"[DEBUG] [{chat_id}] Claude selected sub-code: {chosen_sub_code}")

            # Validate it's actually one of our options
            valid_codes = [r.get("hs_code", "") for r in disco["sub_code_options"]]
            if chosen_sub_code not in valid_codes:
                print(f"[DEBUG] [{chat_id}] Invalid sub-code '{chosen_sub_code}', falling back to first option")
                chosen_sub_code = valid_codes[0] if valid_codes else disco["chosen_hs_code"]

            disco["chosen_sub_code"] = chosen_sub_code
            state["mode"] = "idle"

            # Proceed to XDS detail lookup with the chosen sub-code
            return self._handle_direct_lookup(
                chosen_sub_code,
                f"I want to import products with HS code {chosen_sub_code}",
                chat_id
            )

        except Exception as e:
            print(f"[ERROR] [{chat_id}] Sub-code choice matching failed: {e}")
            import traceback
            traceback.print_exc()
            # Fall back to first option
            first_code = disco["sub_code_options"][0].get("hs_code", "") if disco["sub_code_options"] else disco["chosen_hs_code"]
            disco["chosen_sub_code"] = first_code
            state["mode"] = "idle"
            return self._handle_direct_lookup(first_code, f"HS code {first_code}", chat_id)

    def _extract_product_keyword(self, user_message: str) -> str:
        """Extract product keyword from user message using Claude."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=15,
                timeout=10.0,
                messages=[{
                    "role": "user",
                    "content": f"""Extract the main product keyword(s) from this message for searching a customs database. Return ONLY 1-2 words, no punctuation.

Message: "{user_message}"
Keywords:"""
                }]
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"[ERROR] Keyword extraction failed: {e}")
            return ""

    def _group_results_by_hs_prefix(self, xds_results: list) -> list:
        """Group XDS results by 6-digit HS code prefix."""
        groups = {}
        for r in xds_results:
            prefix = r["hs_code"][:6] if len(r["hs_code"]) >= 6 else r["hs_code"]
            if prefix not in groups:
                count = sum(1 for x in xds_results if x["hs_code"].startswith(prefix))
                match_text = "match" if count == 1 else "matches"
                groups[prefix] = {
                    "hs_code": prefix,
                    "product_name": r["product_name"],
                    "reason": f"{count} {match_text}",
                    "matches": []
                }
            groups[prefix]["matches"].append(r)
        return list(groups.values())[:6]

    def _format_xds_options(self, grouped: list) -> str:
        """Format grouped XDS results as numbered options."""
        lines = ["I found these HS codes in our database:\n"]
        for i, g in enumerate(grouped, 1):
            lines.append(f"Option {i}: {g['hs_code']} — {g['product_name']} ({g['reason']})")
        lines.append("\nWhich one best describes your product?")
        return "\n".join(lines)

    def _is_new_discovery_request(self, user_message: str) -> bool:
        """Check if user is starting a new discovery request while in discovery mode."""
        msg_lower = user_message.lower().strip()

        # Check for "I want to import X" pattern (new discovery request)
        if msg_lower.startswith("i want to import "):
            return True

        # Check for explicit "new request" keywords
        new_request_keywords = [
            "new request",
            "different product",
            "cancel",
            "start over",
            "reset",
            "new query",
            "different import"
        ]

        for keyword in new_request_keywords:
            if keyword in msg_lower:
                return True

        return False

    def _handle_direct_lookup(self, search_term: str, user_message: str, chat_id: str) -> str:
        """Direct HS code or product lookup."""
        state = self.chat_state[chat_id]

        # Clean search term
        search_term = search_term.strip().replace("```", "").replace("\n", "")
        print(f"[DEBUG] [{chat_id}] Direct lookup for: {search_term}")

        # Query XDS
        xds_results = XDSQueryEngine.search(search_term)
        print(f"[DEBUG] [{chat_id}] XDS returned {len(xds_results)} results")
        if xds_results:
            print(f"[DEBUG] [{chat_id}] First result: {xds_results[0]}")

        # Fetch detail if available
        detail_data = None
        if xds_results and xds_results[0].get("detail_url"):
            detail_data = XDSQueryEngine.get_detail(xds_results[0]["detail_url"])
            print(f"[DEBUG] [{chat_id}] Detail page fetched: {bool(detail_data)}")

        # Synthesize response
        response = self._synthesize_compliance_response(
            user_message=user_message,
            xds_results=xds_results,
            detail_data=detail_data,
            chat_id=chat_id
        )
        return response

    def _handle_followup(self, user_message: str, chat_id: str) -> str:
        """Continuation of a previous compliance topic."""
        state = self.chat_state[chat_id]
        history = state["history"]

        system_prompt = f"""{BRAND_VOICE}

---

## Your Task

You are the RACs compliance assistant. The user is asking a follow-up question about a product already discussed.

Use the conversation history and be helpful, concise, and honest. If you need more information from XDS, acknowledge it naturally.

CRITICAL RULES:
1. NEVER invent data not in the conversation
2. If you're unsure, be honest and suggest connecting with a specialist
3. Include exactly ONE call-to-action at the end
4. Keep responses conversational and brief

---

## Conversation History (for context)

{json.dumps(history[-4:], ensure_ascii=False) if history else "New conversation"}

---

## Output

Provide ONLY the RACs response, no preamble. Include one CTA.
"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=800,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"[ERROR] [{chat_id}] Followup response failed: {e}")
            cta = random.choice(CTA_STRATEGY.get("default", {}).get("ctas", ["Let's connect you with a specialist."]))
            return f"That's a great question. {cta}"

    def _synthesize_compliance_response(
        self,
        user_message: str,
        xds_results: list,
        detail_data: Optional[dict],
        chat_id: str
    ) -> str:
        """Synthesize XDS data into RACs-branded compliance response."""
        state = self.chat_state[chat_id]
        history = state["history"]

        xds_summary = self._format_xds_data(xds_results, detail_data)
        print(f"[DEBUG] [{chat_id}] XDS summary:\n{xds_summary}")

        system_prompt = f"""{BRAND_VOICE}

---

## Your Task

You are the RACs compliance assistant. Use the regulatory data below to create a response that:
1. Includes ALL information provided from the detail page sections
2. Improves formatting, tone, and clarity for the user
3. Groups information logically (Products Covered → Certification Requirements → Classification)
4. Never omits any information provided by XDS
5. Never invents data not in XDS

CRITICAL RULES:
1. NEVER mention the data source (user believes this is RACs's own expertise)
2. NEVER remove sections like "Products Covered", "Certification Requirements", "Product Classification" - rephrase but include
3. Include all products, requirements, and classifications mentioned
4. NEVER invent: ISO standards, test procedures, specific timelines, costs beyond what XDS states
5. CRITICAL: User wants 95% match with XDS data - be comprehensive
6. Enhance clarity and professional tone, but do NOT filter or omit information
7. Include EXACTLY ONE call-to-action (CTA) at the end

---

## Available Data from Regulatory Database

{xds_summary}

---

User's Question:
"{user_message}"

Conversation Context:
{json.dumps(history[-2:], ensure_ascii=False) if history else "New conversation"}

---

## Output

Provide ONLY the RACs response. Include all sections from the detail page.
Include exactly one CTA at the end.
Structure: HS Code & Product → Regulation → Products Covered → Certification Requirements → Classification → Notes → CTA
"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )
            synthesized = response.content[0].text.strip()
            print(f"[DEBUG] [{chat_id}] Claude response (first 300 chars): {synthesized[:300]}")
            return synthesized
        except Exception as e:
            print(f"[DEBUG] [{chat_id}] Error synthesizing response: {e}")
            cta = random.choice(CTA_STRATEGY.get("default", {}).get("ctas", ["Let's connect you with a specialist."]))
            return f"I'm having trouble with that. {cta}"

    def _format_xds_data(self, xds_results: list, detail_data: Optional[dict]) -> str:
        """Format XDS results and detail page data for Claude.

        CRITICAL: Include ALL data from XDS verbatim. Claude should enhance formatting
        and voice, but MUST NOT remove any information provided by XDS.
        """
        if not xds_results:
            return "No results found on XDS."

        top_result = xds_results[0]
        summary = f"""
Primary Result from XDS:
- Product: {top_result.get('product_name', 'N/A')}
- HS Code: {top_result.get('hs_code', 'N/A')}
- Regulation: {top_result.get('regulation', 'N/A')}
- Certification Type: {top_result.get('certification_type', 'Not specified')}
"""
        if detail_data:
            summary += "\n" + "="*60 + "\n"
            summary += "DETAIL PAGE INFORMATION (from XDS - INCLUDE ALL SECTIONS):\n"
            summary += "="*60 + "\n"

            # Include ALL sections in order, preserve original text formatting
            if detail_data.get('hs_code_header'):
                summary += f"\n{detail_data.get('hs_code_header')}\n"

            if detail_data.get('regulation_description'):
                summary += f"\n{detail_data.get('regulation_description')}\n"

            if detail_data.get('certificate_of_conformity'):
                summary += f"\n{detail_data.get('certificate_of_conformity')}\n"

            if detail_data.get('products_covered'):
                summary += f"\n{detail_data.get('products_covered')}\n"

            if detail_data.get('certification_requirements'):
                summary += f"\n{detail_data.get('certification_requirements')}\n"

            if detail_data.get('product_classification'):
                summary += f"\n{detail_data.get('product_classification')}\n"

            if detail_data.get('additional_notes'):
                summary += f"\n{detail_data.get('additional_notes')}\n"

            if detail_data.get('disclaimer'):
                summary += f"\n{detail_data.get('disclaimer')}\n"

        summary += "\n" + "="*60
        summary += "\nIMPORTANT: Include all sections above in your response.\n"
        summary += "Improve formatting and tone, but do NOT omit any information.\n"
        summary += "="*60

        return summary

    def _update_history(self, chat_id: str, user_message: str, response: str):
        """Update conversation history, keeping only last 6 turns."""
        state = self.chat_state[chat_id]
        state["history"].append({"role": "user", "content": user_message})
        state["history"].append({"role": "assistant", "content": response})

        if len(state["history"]) > 6:
            state["history"] = state["history"][-6:]


# Keep old process_query for backward compatibility with tests
Orchestrator.process_query = lambda self, user_message, chat_id, turn_count=1: self.process_message(user_message, chat_id)


if __name__ == "__main__":
    # Quick test
    orchestrator = Orchestrator()
    response = orchestrator.process_message(
        user_message="Hi, I want to import some electronic devices but I'm not sure about the HS code",
        chat_id="test_chat"
    )
    print(response)
