#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web-based chat interface for RACS Compliance Bot.
Replaces Telegram with HTTP webhook endpoints.
"""

import os
import sys
import logging
import uuid
import re
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.orchestrator import Orchestrator
from tools.conversation_logger import ConversationLogger

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="RACS Compliance Bot - Web API")

# Enable CORS so Replit website can call these endpoints
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your Replit domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize orchestrator and logger (shared across all requests)
orchestrator = Orchestrator()
logger_service = ConversationLogger()


# Pydantic models for request/response validation
class LeadData(BaseModel):
    """Initial lead capture form data."""
    name: str
    email: str
    phone: str


class ChatMessage(BaseModel):
    """Chat message from the user."""
    session_id: str
    message: str


class SessionResponse(BaseModel):
    """Response when session is created."""
    session_id: str
    initial_message: str
    status: str


class ChatResponse(BaseModel):
    """Response for chat messages."""
    response: str


@app.get("/health")
async def health_check():
    """Health check endpoint for Railway."""
    return {"status": "online", "service": "RACS Compliance Bot Web API"}


@app.post("/webhook/start-session", response_model=SessionResponse)
async def start_session(lead: LeadData):
    """
    Initialize a new chat session with lead data.

    Endpoint for your Replit website to call after form submission.

    Args:
        lead: {name, email, phone}

    Returns:
        {session_id, initial_message, status}

    Example:
        POST https://your-railway-url/webhook/start-session
        Content-Type: application/json

        {
          "name": "John Doe",
          "email": "john@example.com",
          "phone": "+966501234567"
        }
    """
    try:
        # Generate unique session ID
        session_id = str(uuid.uuid4())

        # Create initial message with lead data
        # This pre-fills the conversation so Claude knows who we're talking to
        initial_message = (
            f"My name is {lead.name}, my email is {lead.email}, "
            f"and my phone number is {lead.phone}. "
            f"I'd like to search for product compliance information."
        )

        # Process the initial message through the orchestrator
        # Claude will detect the lead info and acknowledge it
        response = orchestrator.process_message(initial_message, session_id)

        # Save initial conversation
        history = orchestrator.chat_histories.get(session_id, [])
        tools_used = list(orchestrator.tools_used.get(session_id, []))
        logger_service.save_conversation(
            session_id=session_id,
            messages=history,
            user_name=lead.name,
            user_email=lead.email,
            user_phone=lead.phone,
            tools_used=tools_used
        )

        logger.info(f"✓ Session created: {session_id} for {lead.name}")

        return SessionResponse(
            session_id=session_id,
            initial_message=response,
            status="session_created"
        )

    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _extract_user_info(history: list) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract user name, email, and phone from conversation history (preserving original case)."""
    user_name = None
    user_email = None
    user_phone = None

    name_pattern = re.compile(r"my name is\s+([^,\n]+?)(?:,|$|\s+my\s+email)", re.IGNORECASE)
    email_pattern = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
    phone_pattern = re.compile(r"\+?\d[\d\s\-]{7,}\d")

    for msg in history:
        if msg.get("role") != "user" or not isinstance(msg.get("content"), str):
            continue
        content = msg["content"]

        if user_name is None:
            m = name_pattern.search(content)
            if m:
                user_name = m.group(1).strip()

        if user_email is None:
            m = email_pattern.search(content)
            if m:
                user_email = m.group(0)

        if user_phone is None:
            m = phone_pattern.search(content)
            if m:
                user_phone = m.group(0).strip()

    return user_name, user_email, user_phone


@app.post("/webhook/chat", response_model=ChatResponse)
async def chat_message(chat: ChatMessage):
    """
    Send a message in an active chat session.

    Endpoint for your chat widget to call for each user message.

    Args:
        chat: {session_id, message}

    Returns:
        {response: bot_response_text}

    Example:
        POST https://your-railway-url/webhook/chat
        Content-Type: application/json

        {
          "session_id": "550e8400-e29b-41d4-a716-446655440000",
          "message": "I need to know about HS code 1234"
        }
    """
    try:
        if not chat.session_id or not chat.message:
            raise HTTPException(status_code=400, detail="session_id and message are required")

        # Send message to orchestrator
        response = orchestrator.process_message(chat.message, chat.session_id)

        # Save conversation to database
        history = orchestrator.chat_histories.get(chat.session_id, [])
        tools_used = list(orchestrator.tools_used.get(chat.session_id, []))
        user_name, user_email, user_phone = _extract_user_info(history)

        logger_service.save_conversation(
            session_id=chat.session_id,
            messages=history,
            user_name=user_name,
            user_email=user_email,
            user_phone=user_phone,
            tools_used=tools_used
        )

        logger.info(f"✓ Message processed for session: {chat.session_id}")

        return ChatResponse(response=response)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def main():
    """Start the web server."""
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting RACS Compliance Bot Web API on port {port}...")
    print(f"[*] RACS Compliance Bot Web API is running on http://0.0.0.0:{port}")
    print(f"[*] Health check: GET /health")
    print(f"[*] Start session: POST /webhook/start-session")
    print(f"[*] Chat message: POST /webhook/chat")

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
