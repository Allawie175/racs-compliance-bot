"""OpenRouter-backed orchestrator (default model: openai/gpt-4.1-mini).

Drop-in replacement for tools.orchestrator.Orchestrator. Same public surface:
  - __init__()
  - process_message(message: str, session_id: str) -> str
  - chat_histories: dict[str, list]
  - tools_used: dict[str, set]

History is stored in OpenAI chat-completions format (role/content/tool_calls/tool_call_id).
The conversation_logger serializes this fine via its default-encoder fallback.

Engine selection (LOCAL vs XDS) and Postgres funnel-stage tracking are identical
to the Anthropic orchestrator — we reuse the system prompt builder and the tool
execution helpers from that module so behavior matches.
"""
from __future__ import annotations

import os
import json
import logging
import ssl
from typing import Optional
from urllib.parse import urlparse, parse_qs

import httpx
from dotenv import load_dotenv

from tools.conversation_logger import ConversationLogger
from tools.orchestrator import (
    Orchestrator as AnthropicOrchestrator,
    BRAND_VOICE,
    CTA_STRATEGY,
    XDSQueryEngine,
)

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# SSL context — keep verification on by default; corp envs can opt out by setting
# OPENROUTER_INSECURE=1 (we hit this on the Windows dev box).
_ssl_ctx = ssl.create_default_context()
if os.getenv("OPENROUTER_INSECURE") == "1":
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE


class OpenRouterOrchestrator:
    """RACS compliance assistant powered by OpenRouter (default: openai/gpt-4.1-mini)."""

    def __init__(self):
        self.api_key = os.environ["OPENROUTER_API_KEY"]
        self.model = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")
        self.chat_histories: dict[str, list] = {}
        self.tools_used: dict[str, set] = {}
        self.product_interests: dict[str, list[str]] = {}
        self.MAX_HISTORY = 40
        self._db = ConversationLogger()
        self._http = httpx.Client(verify=_ssl_ctx, timeout=120.0)
        logger.info(f"OpenRouterOrchestrator initialized with model={self.model}")

    # ---------- System prompt + tools ----------

    def _build_system_prompt(self) -> str:
        # Reuse the Anthropic orchestrator's prompt verbatim so brand voice is identical
        return AnthropicOrchestrator._build_system_prompt(self)  # type: ignore[arg-type]

    @staticmethod
    def _tools_spec() -> list[dict]:
        """OpenAI-shaped tool definitions. Matches the Anthropic tools by description."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_xds",
                    "description": (
                        "Search the Saudi Arabia import compliance database for a product or HS code. "
                        "Returns matching HS codes with product names, regulation names, and detail URLs. "
                        "Pass the query in the SAME LANGUAGE the user used — our database is Arabic-primary, "
                        "so Arabic queries usually have better coverage. If the first call returns 0 hits, "
                        "retry ONCE with a translation to the other language (Arabic ↔ English). "
                        "HS code digits are language-agnostic — pass as-is."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Product name (English) or HS code"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_regulation_detail",
                    "description": (
                        "Fetch full regulation details for a specific product using its detail_url "
                        "from search_xds results. Call this after the user has picked a specific option."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "Detail page URL from search_xds result"},
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "submit_lead",
                    "description": (
                        "Mark this lead as 'requested callback' in the RACS CRM. Only call when the user "
                        "explicitly asks to be contacted by a specialist. Contact info is already on file; "
                        "do NOT re-collect name/email/phone."
                    ),
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
        ]

    # ---------- Tool execution (identical semantics to Anthropic orchestrator) ----------

    @staticmethod
    def _extract_hs_code(url: str) -> Optional[str]:
        try:
            q = parse_qs(urlparse(url).query)
            code = q.get("hscode", [None])[0]
            return code if code else None
        except Exception:
            return None

    def _execute_tool(self, name: str, args: dict, chat_id: str) -> str:
        self.tools_used[chat_id].add(name)
        try:
            if name == "search_xds":
                query = args.get("query", "")
                print(f"[{chat_id}] Tool: search_xds('{query}')")
                results = []
                for page in (1, 2):
                    page_r = XDSQueryEngine.search(query, page=page)
                    if not page_r:
                        break
                    results.extend(page_r)
                self._db.advance_stage(chat_id, "searched")
                if not results:
                    return json.dumps({"error": "No results found", "results": []}, ensure_ascii=False)
                return json.dumps(results, ensure_ascii=False)

            if name == "get_regulation_detail":
                url = args.get("url", "")
                print(f"[{chat_id}] Tool: get_regulation_detail()")
                detail = XDSQueryEngine.get_detail(url)
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

            if name == "submit_lead":
                print(f"[{chat_id}] Tool: submit_lead (callback requested)")
                product_interest = ",".join(self.product_interests.get(chat_id, [])) or None
                ok = self._db.advance_stage(chat_id, "requested_callback", product_interest=product_interest)
                if ok:
                    return json.dumps({"success": True, "message": "Callback request flagged in CRM"}, ensure_ascii=False)
                return json.dumps({"success": False, "message": "Could not flag callback in CRM"}, ensure_ascii=False)

            return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return json.dumps({"error": f"Tool execution failed: {e}"}, ensure_ascii=False)

    # ---------- Main entry ----------

    def process_message(self, user_message: str, chat_id: str) -> str:
        history = self.chat_histories.setdefault(chat_id, [])
        self.tools_used.setdefault(chat_id, set())
        history.append({"role": "user", "content": user_message})
        text = self._run_loop(history, chat_id)
        if len(history) > self.MAX_HISTORY:
            self.chat_histories[chat_id] = history[-self.MAX_HISTORY:]
        return text

    # Backward-compat with the old call sites that used process_query
    def process_query(self, user_message: str, chat_id: str, turn_count: int = 1) -> str:
        return self.process_message(user_message, chat_id)

    def _run_loop(self, history: list, chat_id: str) -> str:
        system_prompt = self._build_system_prompt()
        tools = self._tools_spec()
        max_loops = 8
        last_text = ""

        for _ in range(max_loops):
            messages = [{"role": "system", "content": system_prompt}] + history
            payload = {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "max_tokens": 1024,
            }
            try:
                r = self._http.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://worker-production-5221.up.railway.app",
                        "X-Title": "RACS Compliance Bot",
                    },
                    json=payload,
                )
            except Exception as e:
                logger.exception("OpenRouter request failed")
                return f"I'm having trouble reaching the model. Please try again. ({e})"

            if r.status_code != 200:
                logger.error(f"[{chat_id}] OpenRouter {r.status_code}: {r.text[:300]}")
                return "I encountered an unexpected condition. Please try again."

            data = r.json()
            usage = data.get("usage", {}) or {}
            print(
                f"[{chat_id}] usage model={self.model} in={usage.get('prompt_tokens', 0)} "
                f"out={usage.get('completion_tokens', 0)}"
            )

            choice = data["choices"][0]
            msg = choice["message"]
            tool_calls = msg.get("tool_calls") or []

            # Append assistant message in OpenAI format. content may be None when tool_calls present.
            assistant_msg = {"role": "assistant", "content": msg.get("content")}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            history.append(assistant_msg)

            if tool_calls:
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = self._execute_tool(name, args, chat_id)
                    history.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })
                continue  # loop so the model can read the tool result

            # No tool calls — final reply
            text = (msg.get("content") or "").strip()
            if text:
                return text

            last_tool = self._last_tool_called(history)
            print(f"[{chat_id}] empty response. last_tool={last_tool}")
            if last_tool == "submit_lead":
                return "✅ Done — a RACS specialist will reach out to you using the contact info you shared earlier. Expect a response within one business day."
            last_text = "I'm having trouble with that. Please try again."
            break

        return last_text or "I encountered a loop limit. Please try again."

    @staticmethod
    def _last_tool_called(history: list) -> Optional[str]:
        for msg in reversed(history):
            if not isinstance(msg, dict):
                continue
            calls = msg.get("tool_calls") or []
            if calls:
                return calls[-1].get("function", {}).get("name")
        return None
