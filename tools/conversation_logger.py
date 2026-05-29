#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PostgreSQL conversation logging for RACS Compliance Bot.
Saves conversation history and metadata for analysis.
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional
import psycopg2

logger = logging.getLogger(__name__)


STAGE_PRIORITY = {
    "form_submitted": 1,
    "searched": 2,
    "viewed_regulation": 3,
    "requested_callback": 4,
}


def _serialize_messages(messages: list) -> str:
    """Serialize messages, converting Anthropic SDK content blocks (TextBlock, ToolUseBlock, etc.) to dicts."""

    def encode(obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return str(obj)

    return json.dumps(messages, ensure_ascii=False, default=encode)


class ConversationLogger:
    """Logs conversations to PostgreSQL for analysis."""

    def __init__(self):
        self.db_url = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
        if not self.db_url:
            logger.warning("DATABASE_URL not set - conversation logging disabled")

    def save_conversation(
        self,
        session_id: str,
        messages: list,
        user_name: Optional[str] = None,
        user_email: Optional[str] = None,
        user_phone: Optional[str] = None,
        tools_used: Optional[list] = None
    ) -> bool:
        """
        Save or update a conversation in the database (upsert on session_id).
        Each session gets exactly one row that updates as the conversation grows.
        """
        if not self.db_url:
            return False

        try:
            conn = psycopg2.connect(self.db_url)
            cur = conn.cursor()

            tools_str = ",".join(tools_used) if tools_used else ""
            created_at = datetime.utcnow().isoformat() + "Z"
            messages_json = _serialize_messages(messages)

            cur.execute(
                """
                INSERT INTO conversation_logs (
                    session_id, user_name, user_email, user_phone, messages, tools_used, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE SET
                    user_name = COALESCE(EXCLUDED.user_name, conversation_logs.user_name),
                    user_email = COALESCE(EXCLUDED.user_email, conversation_logs.user_email),
                    user_phone = COALESCE(EXCLUDED.user_phone, conversation_logs.user_phone),
                    messages = EXCLUDED.messages,
                    tools_used = EXCLUDED.tools_used
                """,
                (
                    session_id,
                    user_name,
                    user_email,
                    user_phone,
                    messages_json,
                    tools_str,
                    created_at,
                )
            )

            conn.commit()
            cur.close()
            conn.close()

            logger.info(f"Saved conversation {session_id} to database")
            return True

        except Exception as e:
            print(f"[save_conversation] FAILED for {session_id}: {type(e).__name__}: {e}")
            return False

    def advance_stage(
        self,
        session_id: str,
        new_stage: str,
        product_interest: Optional[str] = None,
    ) -> bool:
        """
        Advance a conversation's funnel stage. Only moves forward — never regresses.
        Stages: form_submitted -> searched -> viewed_regulation -> requested_callback.
        Sets callback_requested_at to now() when new_stage is requested_callback.
        """
        if not self.db_url:
            return False
        if new_stage not in STAGE_PRIORITY:
            print(f"[advance_stage] Unknown stage: {new_stage}")
            return False

        try:
            conn = psycopg2.connect(self.db_url)
            cur = conn.cursor()

            new_priority = STAGE_PRIORITY[new_stage]
            stage_cases = " ".join(
                f"WHEN stage = '{s}' THEN {p}" for s, p in STAGE_PRIORITY.items()
            )

            cur.execute(
                f"""
                UPDATE conversation_logs
                SET
                    stage = CASE
                        WHEN (CASE {stage_cases} ELSE 0 END) < %s THEN %s
                        ELSE stage
                    END,
                    product_interest = COALESCE(%s, product_interest),
                    callback_requested_at = CASE
                        WHEN %s = 'requested_callback' AND callback_requested_at IS NULL
                        THEN NOW()
                        ELSE callback_requested_at
                    END
                WHERE session_id = %s
                """,
                (new_priority, new_stage, product_interest, new_stage, session_id),
            )

            conn.commit()
            cur.close()
            conn.close()
            return True

        except Exception as e:
            print(f"[advance_stage] FAILED for {session_id}: {type(e).__name__}: {e}")
            return False

    def get_conversation(self, session_id: str) -> Optional[dict]:
        """Retrieve a conversation from the database."""
        if not self.db_url:
            return None

        try:
            conn = psycopg2.connect(self.db_url)
            cur = conn.cursor()

            cur.execute(
                "SELECT id, session_id, user_name, user_email, user_phone, messages, tools_used, created_at FROM conversation_logs WHERE session_id = %s",
                (session_id,)
            )

            row = cur.fetchone()
            cur.close()
            conn.close()

            if not row:
                return None

            return {
                "id": row[0],
                "session_id": row[1],
                "user_name": row[2],
                "user_email": row[3],
                "user_phone": row[4],
                "messages": row[5],
                "tools_used": row[6].split(",") if row[6] else [],
                "created_at": row[7],
            }

        except Exception as e:
            logger.error(f"Failed to retrieve conversation {session_id}: {e}")
            return None

    def list_conversations(self, limit: int = 100) -> list:
        """List recent conversations."""
        if not self.db_url:
            return []

        try:
            conn = psycopg2.connect(self.db_url)
            cur = conn.cursor()

            cur.execute(
                """
                SELECT session_id, user_name, user_email, user_phone, tools_used, created_at
                FROM conversation_logs
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,)
            )

            rows = cur.fetchall()
            cur.close()
            conn.close()

            return [
                {
                    "session_id": row[0],
                    "user_name": row[1],
                    "user_email": row[2],
                    "user_phone": row[3],
                    "tools_used": row[4].split(",") if row[4] else [],
                    "created_at": row[5],
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"Failed to list conversations: {e}")
            return []
