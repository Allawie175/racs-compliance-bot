#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import logging
import sys
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from telegram.constants import ParseMode

# Load environment variables
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.orchestrator import Orchestrator

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize orchestrator
orchestrator = Orchestrator()


class RACSBot:
    """RACs compliance chatbot for Telegram."""

    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command — warm welcome."""
        response = orchestrator.process_message("hello", str(update.effective_chat.id))
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)

    @staticmethod
    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Universal message handler. The orchestrator detects intent and routes automatically.
        No commands needed — feels like chatting with a human consultant.
        """
        user_message = update.message.text
        chat_id = str(update.effective_chat.id)

        # Show typing indicator
        await update.message.chat.send_action("typing")

        try:
            # Send to orchestrator — it detects intent and handles everything
            response = orchestrator.process_message(user_message, chat_id)
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            await update.message.reply_text(
                "I encountered an issue processing that message. "
                "Could you try rephrasing, or type 'contact' to reach the RACs team directly?"
            )


def main():
    """Start the Telegram bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    # Create application
    application = Application.builder().token(token).build()

    # /start command for backward compatibility
    application.add_handler(CommandHandler("start", RACSBot.start))

    # Single universal message handler — no /ask, /help, /contact commands needed
    # The bot detects intent automatically from natural conversation
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, RACSBot.handle_message))

    # Start bot
    logger.info("RACs Compliance Bot is running (intent-driven mode)...")
    print("[*] RACs Compliance Bot is polling. Press Ctrl+C to stop.")

    application.run_polling()


if __name__ == "__main__":
    main()
