#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import logging
import sys
import asyncio
import ssl
import certifi
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from telegram.constants import ParseMode

# Load environment variables
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.orchestrator import Orchestrator
from bot.lead_capture import LeadCapture

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize orchestrator and lead capture
orchestrator = Orchestrator()
lead_capture = LeadCapture()

# Conversation states for lead capture
ASKING_FOR_NAME, ASKING_FOR_EMAIL, ASKING_FOR_PHONE, CONFIRMING = range(4)


class RACSBot:
    """RACs compliance chatbot for Telegram."""

    WELCOME_MESSAGE = """🛡️ Welcome to RACs Compliance Assistant!

I'm here to help you understand import regulations and certification requirements for products entering Saudi Arabia.

**What I can help with:**
✓ Product certification requirements
✓ Testing standards and procedures
✓ Timeline and cost estimates
✓ Next steps and expert consultations

**Commands:**
/ask `<question>` — Ask about any product or compliance requirement
/contact — Get RACs contact information
/help — Learn how to use this bot
/start — See this welcome message

**Example:** `/ask What do I need to import electric scooters?`

Let's help you navigate compliance smoothly. What questions do you have?"""

    CONTACT_MESSAGE = """📞 **RACs Contact Information**

**Phone:** {phone}
**Email:** {email}
**Schedule a consultation:** {calendly}

Our team responds within 24 hours and offers a free initial assessment.

Have more compliance questions? Use `/ask <question>` anytime."""

    HELP_MESSAGE = """📚 **How to Use RACs Compliance Assistant**

1. **Ask questions** using `/ask <your question>`
   Examples:
   - `/ask What's required to import lithium batteries?`
   - `/ask How much does certification cost?`
   - `/ask Can I get expedited certification?`

2. **Get my contact info** with `/contact`
   Schedule a free consultation or call our team.

3. **Follow-up questions** — Just type naturally!
   The bot remembers context from earlier in the conversation.

4. **Lead qualification** — After a few exchanges, you can request a specialist callback.
   Simply type "yes" when offered.

**Example conversation:**
- You: `/ask I'm importing wireless headphones`
- Bot: [provides certification requirements]
- You: `What's the timeline?`
- Bot: [answers with timeline + CTA]
- You: `sounds good, connect me with someone`
- Bot: [captures your info + schedules callback]

**Important:** This bot provides information based on current Saudi import regulations.
For complex products, always schedule a consultation with our experts.

Need help? Use `/contact` to reach our team directly."""

    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        await update.message.reply_text(RACSBot.WELCOME_MESSAGE)

    @staticmethod
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        await update.message.reply_text(RACSBot.HELP_MESSAGE)

    @staticmethod
    async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /contact command."""
        phone = os.getenv("RACS_CONTACT_PHONE", "+966-XX-XXXX-XXXX")
        email = os.getenv("RACS_CONTACT_EMAIL", "compliance@racs.example")
        calendly = os.getenv("RACS_CALENDLY_LINK", "https://calendly.com/racs")

        message = RACSBot.CONTACT_MESSAGE.format(
            phone=phone,
            email=email,
            calendly=calendly
        )
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    @staticmethod
    async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /ask <question> command."""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        # Extract question from command
        if not context.args:
            await update.message.reply_text(
                "Please provide your question.\n\n"
                "Usage: `/ask What do I need to import [product]?`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        user_message = " ".join(context.args)

        # Show typing indicator
        await update.message.chat.send_action("typing")

        try:
            # Get turn count from context
            turn_count = context.user_data.get("turn_count", 1)
            context.user_data["turn_count"] = turn_count + 1

            # Process query through orchestrator
            response = orchestrator.process_query(
                user_message=user_message,
                chat_id=str(chat_id),
                turn_count=turn_count
            )

            # Send response with markdown formatting
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)

            # After 3 turns, offer lead capture
            if turn_count >= 3 and context.user_data.get("lead_captured") is None:
                await update.message.reply_text(
                    "Want RACs to handle this for you? I can connect you with a specialist who can provide personalized guidance.\n\nType **yes** to get started, or keep asking questions.",
                    parse_mode=ParseMode.MARKDOWN
                )

        except Exception as e:
            logger.error(f"Error processing query: {e}")
            await update.message.reply_text(
                "Sorry, I encountered an error processing your question. "
                "Please try again or contact RACs directly: /contact"
            )

    @staticmethod
    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle regular messages (follow-ups, lead capture responses)."""
        user_message = update.message.text.lower()
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        # Check if user is responding to lead capture offer
        if "yes" in user_message and context.user_data.get("lead_captured") is None:
            context.user_data["lead_captured"] = True
            await update.message.reply_text(
                "Great! I'll connect you with a RACs specialist.\n\n"
                "What's your name?"
            )
            context.user_data["awaiting_name"] = True
            return

        # Lead capture: collect name
        if context.user_data.get("awaiting_name"):
            context.user_data["name"] = update.message.text
            context.user_data["awaiting_name"] = False
            await update.message.reply_text("Thanks! What's your email address?")
            context.user_data["awaiting_email"] = True
            return

        # Lead capture: collect email
        if context.user_data.get("awaiting_email"):
            context.user_data["email"] = update.message.text
            context.user_data["awaiting_email"] = False
            await update.message.reply_text("And your phone number?")
            context.user_data["awaiting_phone"] = True
            return

        # Lead capture: collect phone
        if context.user_data.get("awaiting_phone"):
            context.user_data["phone"] = update.message.text
            context.user_data["awaiting_phone"] = False

            # Submit lead to Airtable
            lead_data = {
                "name": context.user_data.get("name", ""),
                "email": context.user_data.get("email", ""),
                "phone": context.user_data.get("phone", ""),
                "product_interest": context.user_data.get("product_interest", "General"),
                "chat_id": str(chat_id)
            }

            success = lead_capture.submit_lead(lead_data)

            if success:
                phone = os.getenv("RACS_CONTACT_PHONE", "+966-XX-XXXX-XXXX")
                await update.message.reply_text(
                    f"Perfect! 🎯 We've got your information.\n\n"
                    f"Our team will be in touch within 24 hours to discuss your specific requirements.\n\n"
                    f"In the meantime, feel free to call us at {phone} or keep asking questions using `/ask`.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    "We had trouble saving your information, but our team will still reach out. "
                    "Alternatively, use `/contact` to reach us directly."
                )
            return

        # Regular follow-up question (not lead capture)
        turn_count = context.user_data.get("turn_count", 1)
        context.user_data["turn_count"] = turn_count + 1

        # Show typing indicator
        await update.message.chat.send_action("typing")

        try:
            response = orchestrator.process_query(
                user_message=user_message,
                chat_id=str(chat_id),
                turn_count=turn_count
            )
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Error processing follow-up: {e}")
            await update.message.reply_text(
                "I encountered an issue processing that. "
                "Use `/ask [question]` for a fresh query or `/contact` to reach our team."
            )


def main():
    """Start the Telegram bot."""
    # Ensure event loop exists on Windows
    if sys.platform == 'win32':
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                asyncio.set_event_loop(asyncio.new_event_loop())
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

    # Configure SSL certificates
    os.environ['SSL_CERT_FILE'] = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

    # Workaround for Windows SSL certificate verification issues
    # Set environment variable to use certifi certs
    os.environ['PYTHONHTTPSVERIFY'] = '1'

    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    # Setup SSL context with proper certificates
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    # Create application
    application = Application.builder().token(token).build()

    # Command handlers
    application.add_handler(CommandHandler("start", RACSBot.start))
    application.add_handler(CommandHandler("help", RACSBot.help_command))
    application.add_handler(CommandHandler("contact", RACSBot.contact_command))
    application.add_handler(CommandHandler("ask", RACSBot.ask_command))

    # Message handler for follow-ups and lead capture
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, RACSBot.handle_message))

    # Start bot
    logger.info("RACs Compliance Bot is running...")
    print("[*] RACs Compliance Bot is polling. Press Ctrl+C to stop.")

    application.run_polling()


if __name__ == "__main__":
    main()
