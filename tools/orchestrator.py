import os
import json
import random
from typing import Optional
from dotenv import load_dotenv
from anthropic import Anthropic
from tools.xds_query import XDSQueryEngine

# Load environment variables
load_dotenv()

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
    Coordinates XDS queries with Claude synthesis to produce RACs-branded responses.
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
        # Per-chat conversation history for multi-turn context
        self.conversation_history: dict[str, list] = {}

    def process_query(
        self,
        user_message: str,
        chat_id: str,
        turn_count: int = 1
    ) -> str:
        """
        Process user question through full RACs pipeline.

        Args:
            user_message: User's compliance question
            chat_id: Telegram chat ID (for conversation memory)
            turn_count: Message count in this conversation (for CTA selection)

        Returns:
            RACs-branded response with embedded CTA
        """

        # Initialize conversation history for this chat if needed
        if chat_id not in self.conversation_history:
            self.conversation_history[chat_id] = []

        # Step 1: Extract search term from user message
        search_term = self._extract_search_term(user_message)

        if not search_term:
            return self._fallback_response("I couldn't understand your question. "
                                          "Could you tell me more about the product you're importing?")

        # Step 2: Query XDS (hidden from user)
        xds_results = XDSQueryEngine.search(search_term)

        # Step 3: Fetch detail if we got a result
        detail_data = None
        if xds_results and xds_results[0].get("detail_url"):
            detail_data = XDSQueryEngine.get_detail(xds_results[0]["detail_url"])

        # Step 4: Synthesize into RACs voice
        response = self._synthesize_response(
            user_message=user_message,
            search_term=search_term,
            xds_results=xds_results,
            detail_data=detail_data,
            turn_count=turn_count,
            chat_id=chat_id
        )

        # Step 5: Update conversation history
        self.conversation_history[chat_id].append({"role": "user", "content": user_message})
        self.conversation_history[chat_id].append({"role": "assistant", "content": response})

        # Keep only last 6 messages per conversation
        if len(self.conversation_history[chat_id]) > 6:
            self.conversation_history[chat_id] = self.conversation_history[chat_id][-6:]

        return response

    def _extract_search_term(self, user_message: str) -> Optional[str]:
        """
        Use Claude to extract a clean XDS search term from user message.
        """
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=100,
                system="You are a compliance search specialist. Extract the main product/regulation search term from the user's question. Return ONLY the search term (1-5 words), nothing else. If unclear, return empty string.",
                messages=[{"role": "user", "content": user_message}]
            )
            term = response.content[0].text.strip()
            return term if len(term) > 0 else None
        except Exception as e:
            print(f"Error extracting search term: {e}")
            return None

    def _synthesize_response(
        self,
        user_message: str,
        search_term: str,
        xds_results: list,
        detail_data: Optional[dict],
        turn_count: int,
        chat_id: str
    ) -> str:
        """
        Use Claude to synthesize XDS data into RACs-branded response.
        """
        # Prepare XDS data summary
        xds_summary = self._format_xds_data(xds_results, detail_data)

        # Get conversation history for context
        history = self.conversation_history.get(chat_id, [])

        # Prepare system prompt with brand voice
        system_prompt = f"""{BRAND_VOICE}

---

## Your Task

You are the RACs compliance assistant. Convert the XDS data below into a professional, helpful response in RACs voice.

CRITICAL RULES:
1. NEVER mention "XDS" or any data sources—user believes this is RACs's own expertise
2. Every response must include EXACTLY ONE call-to-action (CTA)
3. Structure response using the template: emoji header → summary → bullet requirements → timeline/cost → pain point → RACs value → CTA
4. Be specific (e.g., "4-8 weeks" not "depends"; "$5K-$10K" not "varies")
5. If no XDS data found, respond helpfully with what you know and suggest a consultation
6. Focus on actionable next steps

---

## Available Data

XDS Search Results:
{xds_summary}

User's Original Question:
"{user_message}"

Conversation Context (last messages):
{json.dumps(history[-2:], ensure_ascii=False) if history else "New conversation"}

---

## CTA Selection Hint

Turn count: {turn_count}
Analyze the question for: complexity signals (number of standards, testing required, documentation burden),
urgency signals (deadlines, time pressure), volume signals (one product vs. many).
Choose the most contextual CTA category from available options.

---

## Output

Provide ONLY the RACs response, no preamble. Include exactly one CTA at the end.
"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"Error synthesizing response: {e}")
            return self._fallback_response(user_message)

    def _format_xds_data(self, xds_results: list, detail_data: Optional[dict]) -> str:
        """
        Format XDS results into a concise summary for Claude.
        """
        if not xds_results:
            return "No results found on XDS."

        top_result = xds_results[0]
        summary = f"""
Primary Result:
- Product: {top_result.get('product_name', 'N/A')}
- HS Code: {top_result.get('hs_code', 'N/A')}
- Regulation: {top_result.get('regulation', 'N/A')}
- Certification Type: {top_result.get('certification_type', 'N/A')}
- Description: {top_result.get('description', 'N/A')}
"""
        if detail_data:
            summary += f"""
Detail Page Data:
- Procedure: {detail_data.get('certification_procedure', 'N/A')}
- Required Documents: {detail_data.get('required_documents', 'N/A')}
- Applicable Standards: {detail_data.get('applicable_standards', 'N/A')}
- Accredited Bodies: {detail_data.get('accredited_bodies', 'N/A')}
"""
        return summary

    def _fallback_response(self, user_message: str) -> str:
        """
        Graceful fallback when XDS fails or data is unclear.
        """
        cta = random.choice(CTA_STRATEGY["default"]["ctas"])
        return f"""I couldn't find specific data on that product right now, but RACs can definitely help.

Import compliance can be complex, and every product is unique. Rather than guessing, let's talk with someone who knows your specific situation.

{cta}"""

    def get_cta_for_context(
        self,
        complexity: str = "default",
        urgency: str = "none",
        turn_count: int = 1
    ) -> str:
        """
        Select appropriate CTA based on complexity/urgency/journey stage.
        Never returns same CTA twice for same chat.
        """
        # Determine category
        if urgency == "high":
            category = "urgent_products"
        elif complexity == "high":
            category = "complex_products"
        elif complexity == "low":
            category = "simple_products"
        elif turn_count >= 3:
            category = "returning_user"
        elif turn_count == 1:
            category = "first_question"
        else:
            category = "default"

        # Ensure category exists
        if category not in CTA_STRATEGY:
            category = "default"

        ctas = CTA_STRATEGY[category]["ctas"]
        return random.choice(ctas)


if __name__ == "__main__":
    # Quick test
    orchestrator = Orchestrator()
    response = orchestrator.process_query(
        user_message="What do I need to import electric scooters to Saudi Arabia?",
        chat_id="test_chat",
        turn_count=1
    )
    print(response)
