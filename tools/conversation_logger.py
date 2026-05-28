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
from psycopg2.extras import Json
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class ConversationLogger:
    """Logs conversations to PostgreSQL for analysis."""

    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        print(f"[ConversationLogger] DATABASE_URL: {self.db_url[:50] if self.db_url else 'NOT SET'}...")
        if not self.db_url:
            print("[ConversationLogger] WARNING: DATABASE_URL not set - conversation logging disabled")
            self.db_url = None

    def save_conversation(
        self,
        session_id: str,
        messages: list,
        user_name: Optional[str] = None,
        user_email: Optional[str] = None,
        tools_used: Optional[list] = None
    ) -> bool:
        """
        Save a conversation to the database.

        Args:
            session_id: Unique session identifier
            messages: List of message dicts with role and content
            user_name: User's name if captured
            user_email: User's email if captured
            tools_used: List of tool names called during conversation

        Returns:
            True if successful, False otherwise
        """
        print(f"[save_conversation] Called for session {session_id}, db_url set: {bool(self.db_url)}")
        if not self.db_url:
            print(f"[save_conversation] DATABASE_URL not set, returning False")
            return False

        try:
            # Connect to database
            conn = psycopg2.connect(self.db_url)
            cur = conn.cursor()

            # Format tools_used as comma-separated string
            tools_str = ",".join(tools_used) if tools_used else ""

            # Format timestamp
            created_at = datetime.utcnow().isoformat() + "Z"

            # Insert conversation
            cur.execute(
                """
                INSERT INTO conversation_db (
                    session_id, user_name, user_email, messages, tools_used, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    user_name,
                    user_email,
                    json.dumps(messages, ensure_ascii=False),
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
            logger.error(f"Failed to save conversation {session_id}: {e}")
            return False

    def get_conversation(self, session_id: str) -> Optional[dict]:
        """
        Retrieve a conversation from the database.

        Args:
            session_id: Unique session identifier

        Returns:
            Conversation dict or None if not found
        """
        if not self.db_url:
            return None

        try:
            conn = psycopg2.connect(self.db_url)
            cur = conn.cursor()

            cur.execute(
                "SELECT * FROM conversation_db WHERE session_id = %s",
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
                "messages": json.loads(row[4]),
                "tools_used": row[5].split(",") if row[5] else [],
                "created_at": row[6],
            }

        except Exception as e:
            logger.error(f"Failed to retrieve conversation {session_id}: {e}")
            return None

    def list_conversations(self, limit: int = 100) -> list:
        """
        List recent conversations.

        Args:
            limit: Maximum number of conversations to return

        Returns:
            List of conversation dicts
        """
        if not self.db_url:
            return []

        try:
            conn = psycopg2.connect(self.db_url)
            cur = conn.cursor()

            cur.execute(
                """
                SELECT session_id, user_name, user_email, tools_used, created_at
                FROM conversation_db
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
                    "tools_used": row[3].split(",") if row[3] else [],
                    "created_at": row[4],
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"Failed to list conversations: {e}")
            return []
