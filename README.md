# RACs Compliance Telegram Chatbot

A white-label compliance assistant that converts curious users into qualified leads through intelligent, RACs-branded responses powered by live XDS data.

## Overview

### What It Does
- **User sees**: Natural conversation with a compliance expert, no commands needed
- **We do**: Detect intent, query XDS invisibly, synthesize into RACs voice
- **Result**: Seamless compliance guidance + lead conversion

### Architecture (Intent-Driven)

```
User Message (Telegram) — Natural conversation, no commands
         ↓
    Claude Intent Detector
         ├── greeting → welcome
         ├── discovery → ask clarifying questions → propose HS codes → query XDS
         ├── direct_lookup → query XDS immediately
         ├── followup → answer from context
         ├── lead_capture → name → email → phone → Airtable
         └── contact_info → show RACs contact details
         ↓
    RACs Orchestrator
         ├── Query XDS (if needed)
         ├── Synthesize into RACs voice
         └── Select contextual CTA
         ↓
   Telegram User (Sees professional response + single CTA)

## Components

| Component | Purpose | File |
|---|---|---|
| **XDS Query Engine** | HTTP client for XDS search | `tools/xds_query.py` |
| **Orchestrator** | Claude-powered synthesis to RACs voice | `tools/orchestrator.py` |
| **Telegram Bot** | Command handlers, user interface | `bot/telegram_bot.py` |
| **Lead Capture** | Airtable integration for CRM push | `bot/lead_capture.py` |
| **Brand Voice** | Tone guidelines, response templates, CTA pool | `brand/racs_voice.md` |
| **CTA Strategy** | Context-driven CTA rotation | `config/cta_strategy.json` |
| **Workflow SOP** | Detailed process documentation | `workflows/compliance_query.md` |

## Setup

### 1. Clone & Install

```bash
git clone <repo>
cd "Racs telegram"
pip install -r requirements.txt
```

### 2. Environment Configuration

Copy `.env` and fill in credentials:

```bash
# .env file
TELEGRAM_BOT_TOKEN=<your_bot_token_from_BotFather>
ANTHROPIC_API_KEY=<your_claude_api_key>

# RACs Contact (appears in /contact command)
RACS_CONTACT_PHONE=+966-XX-XXXX-XXXX
RACS_CONTACT_EMAIL=compliance@racs.example
RACS_CALENDLY_LINK=https://calendly.com/racs

# Airtable (optional, for lead capture)
AIRTABLE_API_KEY=<your_airtable_token>
AIRTABLE_BASE_ID=<your_base_id>
AIRTABLE_TABLE_NAME=Leads

# XDS (already configured)
XDS_BASE_URL=https://xds-solutions.com/certification/saudi-arabia/hs-code-search-tool
```

**Getting credentials:**

- **Telegram Token**: Message @BotFather, create bot, copy token
- **Claude API Key**: [Get from Anthropic Console](https://console.anthropic.com)
- **Airtable Token**: [Get from Airtable Account Settings](https://airtable.com/account) (optional, for lead capture)

### 3. Test XDS Connection

```bash
python tools/xds_query.py
```

Expected output:
```
Testing XDS query engine...
Found 8 results
First result: {'product_name': '...', 'hs_code': '...', ...}
```

### 4. Test Orchestrator

```bash
python tools/orchestrator.py
```

Expected output:
```
🛴 Electric scooters fall under Saudi Technical Regulation...
✓ Certification Type: Type A
...
Ready to get started? RACs handles all the paperwork.
```

### 5. Run Bot

```bash
python bot/telegram_bot.py
```

Expected output:
```
🤖 RACs Compliance Bot is running...
Press Ctrl+C to stop.
```

Open Telegram, find your bot, and test (just type naturally — no commands needed):
- `hello` or `hi` → Bot gives warm welcome
- `I want to import fabric but not sure about HS code` → Bot asks clarifications, proposes codes
- `850410000000` → Bot queries regulations immediately
- `connect me with a specialist` → Bot asks for name/email/phone

## Usage Examples

### Example 1: Discovery Mode (User doesn't know HS code)

```
User:
I want to import LED displays for commercial use, but I'm not sure about the HS code.

Bot:
Great! I'll help you find the right code. A few quick questions:

Are these LED displays fixed installations (like billboards) or portable units?

User:
Fixed installations, like digital signage.

Bot:
Got it. Are these using modular LED panels or complete integrated units?

User:
Modular panels that can be configured.

Bot:
Based on what you've told me, here are the likely HS codes:

**Option 1: 940360**
Product: Parts and accessories for electric lighting fixtures
Why: Generic LED lighting component classification

**Option 2: 854380**
Product: Light emitting diodes (LED)
Why: Specific LED component classification

**Option 3: 852921**
Product: Parts of electronic switching devices
Why: If these have integrated control circuitry

Which one sounds right? (Just reply with the option number or the HS code)

User:
Option 2

Bot:
Perfect! Let me check the regulations for LED components...

[Bot queries XDS with 854380, returns regulations]

⚡ LED modules fall under the **Technical Regulation for Electrical Products**...
```

### Example 2: Direct HS Code Lookup

```
User:
I have HS code 8517120000. What's required to import this to Saudi Arabia?

Bot:
[Bot immediately queries XDS with 8517120000]

📱 Telephone switching equipment requires **SABER Certification**...
```

### Example 3: Lead Capture

```
User:
Can you connect me with a specialist? This is getting complex.

Bot:
I'd love to connect you with a RACs specialist. What's your name?

User:
Ahmed Al-Rashid

Bot:
Thanks, Ahmed! What's your email address?

User:
ahmed@importco.example

Bot:
And your phone number?

User:
+966-50-1234567

Bot:
✅ Thank you, Ahmed!

A RACs specialist will reach out to you at ahmed@importco.example or +966-50-1234567 
within 24 hours.

Looking forward to helping you navigate Saudi Arabia's import requirements.
```

## How the Bot Works: Intent Detection

The bot automatically detects what you want to do, no commands needed:

| Intent | Triggered by | Bot Response |
|--------|---|---|
| **Greeting** | "hi", "hello", "hey", starting fresh | Warm welcome explaining capabilities |
| **Discovery** | "I want to import X but don't know the HS code" | Ask 2 clarifying questions → propose 2-3 codes → query XDS when user picks one |
| **Direct Lookup** | "8517120000" or "lithium batteries" | Query XDS immediately, return regulations |
| **Follow-up** | "What about timeline?", "Will this cost more?" | Answer from conversation context, reference prior XDS data |
| **Lead Capture** | "connect me", "call me", "I want to speak to someone" | Collect name → email → phone → submit to Airtable |
| **Contact Info** | "How do I reach RACs?" | Show phone, email, Calendly link |

## Brand Voice

The bot speaks like a **trusted compliance expert**, not a generic AI.

### ✓ Do This
- **Use only XDS data** — be accurate, not inventive
- Acknowledge regulatory complexity and RACs value
- Be honest about unknowns: "The specifics depend on your exact product"
- Include exactly ONE CTA per response
- Feel like a human consultant, not an AI

### ✗ Don't Do This
- Mention XDS as a data source (user believes this is RACs expertise)
- Invent timelines, costs, or testing procedures
- Use unexplained jargon
- Repeat CTAs or mention multiple contact methods in one message
- Pretend to have all answers — escalate to specialists when appropriate

[Full brand guidelines in `brand/racs_voice.md`]

## CTA Strategy

Every response includes exactly **one call-to-action**, selected based on:

| Signal | Category | CTA Example |
|---|---|---|
| Few standards | `simple_products` | "Ready to get started? RACs handles all the paperwork." |
| Multiple standards | `complex_products` | "This requires expert guidance. Schedule a consultation." |
| User mentions deadline | `urgent_products` | "Tight timeline? RACs can compress by 30-40%." |
| Turn 1 | `first_question` | "You're asking the right questions. More?" |
| Turn 3+ | `returning_user` | "Time to move forward with an expert?" |

[Full CTA library in `config/cta_strategy.json`]

## Lead Capture

After 3+ exchanges, bot offers to connect user with specialist.

### Flow
1. Bot: "Want RACs to handle this? I can connect you."
2. User: "Yes"
3. Bot: Collects name, email, phone
4. Bot: Pushes to Airtable
5. RACs Sales: Reaches out within 24h

### Airtable Record Structure
```
{
  "Name": "John Importer",
  "Email": "john@importco.com",
  "Phone": "+966-XX-XXXX-XXXX",
  "Product Interest": "Lithium Batteries",
  "Chat ID": "123456789",
  "Source": "Telegram Bot",
  "Captured At": "2026-05-09T14:30:00Z"
}
```

### Optional
If Airtable not configured, lead capture is disabled gracefully (user still gets contact info).

## File Structure

```
.
├── .env                           # API keys (gitignored)
├── brand/
│   └── racs_voice.md              # Brand guidelines & CTA library
├── config/
│   └── cta_strategy.json          # Context-driven CTA rotation
├── tools/
│   ├── xds_query.py               # XDS HTTP client + parser
│   └── orchestrator.py            # Claude synthesis engine
├── bot/
│   ├── telegram_bot.py            # Bot entry point
│   └── lead_capture.py            # Airtable integration
├── workflows/
│   └── compliance_query.md        # Process documentation
├── .tmp/
│   └── errors.log                 # Error logging
└── README.md                      # This file
```

## Development & Testing

### Run Tests Locally

```bash
# Test XDS integration
python tools/xds_query.py

# Test orchestrator
python tools/orchestrator.py

# Test bot (requires Telegram token)
python bot/telegram_bot.py
```

### Debug Mode

Set `LOG_LEVEL=DEBUG` in `.env` to see full API interactions.

```bash
LOG_LEVEL=DEBUG python bot/telegram_bot.py
```

### Common Issues

| Issue | Solution |
|---|---|
| XDS not responding | Check `XDS_BASE_URL` in `.env`; verify network connectivity |
| Claude API errors | Check `ANTHROPIC_API_KEY` in `.env`; verify rate limits |
| Telegram message not sent | Check `TELEGRAM_BOT_TOKEN` in `.env` |
| Airtable lead not saved | Check `AIRTABLE_API_KEY`, `BASE_ID`, `TABLE_NAME` in `.env` |

## Deployment

### Production Checklist

- [ ] Test intent detection (greeting, discovery, lookup, followup, lead_capture)
- [ ] Test HS code discovery flow end-to-end (2 clarifications → 3 codes → pick → XDS)
- [ ] Test direct HS code lookup (pasted code works)
- [ ] Test lead capture flow (name → email → phone → Airtable)
- [ ] Verify RACs voice (no XDS mention, professional tone, single CTA per response)
- [ ] Verify no hallucination (only XDS data, no invented costs/timelines)
- [ ] Set up monitoring for `.tmp/errors.log`
- [ ] Test with Railway deployment (auto-deploys on GitHub push)
- [ ] Brief RACs sales team on lead format + follow-up SLA

### Cloud Deployment

**Railway (Current)**
1. Connect GitHub repo to Railway: https://railway.app
2. Railway auto-deploys on every GitHub push
3. Set environment variables in Railway dashboard:
   - Go to project settings → Variables
   - Add: `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, `XDS_BASE_URL`, `RACS_CONTACT_PHONE`, `RACS_CONTACT_EMAIL`, etc.
4. Bot runs via `Procfile`: `worker: python bot/telegram_bot.py`

**Alternative: Self-Hosted (VPS)**
- Run `python bot/telegram_bot.py` in tmux/screen
- Monitor with systemd service
- Rotate logs daily

**Legacy: AWS Lambda + API Gateway**
- Wrap `telegram_bot.py` in Lambda handler
- Configure webhook (faster than polling)
- Store conversation state in DynamoDB

## Monitoring & Analytics

### Key Metrics
- **Usage**: Questions per day, active users
- **Engagement**: Average conversation length (turns)
- **Conversion**: Users who click CTA → leads submitted
- **Quality**: Error rate, response time

### Logging
- **Errors**: `.tmp/errors.log` (XDS, Claude, Airtable failures)
- **Usage**: Telegram bot built-in analytics
- **Leads**: Airtable form submissions (track conversion)

## Architecture Decisions

| Decision | Rationale |
|---|---|
| Claude Sonnet 4.6 | Best cost/quality for real-time chat |
| BeautifulSoup for XDS | No public API; HTML parsing is reliable |
| In-memory conversation history | Simple MVP; scale to DB if needed |
| Airtable (not Sheets) | Simpler REST API, better for CRM integration |
| MarkdownV2 formatting | Telegram native, better readability |

## Future Roadmap

### Phase 2
- [ ] Persistent database for conversation history
- [ ] Advanced NLP for faster product matching
- [ ] A/B testing on CTA variants (measure conversion)
- [ ] Proactive recommendations ("You might also need X")

### Phase 3
- [ ] Multi-language support (AR, FR)
- [ ] WhatsApp bot version
- [ ] Integration with RACs CRM (HubSpot, Pipedrive)
- [ ] Chatbot analytics dashboard

## Support

**For bot issues:**
- Check `.tmp/errors.log`
- Run tests: `python tools/xds_query.py`
- Check `.env` credentials

**For RACs team:**
- Lead format in Airtable: name, email, phone, product_interest, chat_id, source, timestamp
- Lead capture disabled if Airtable not configured
- Triggered when user says "connect me", "call me", or similar intent

## License

Internal use only. All user data encrypted in transit.

---

**Last Updated:** 2026-05-09 (Intent-driven refactor: natural conversation, HS code discovery, automatic routing)
**Maintainer:** RACs Compliance Team  
**Status:** ✅ Production Ready

## Latest Changes (2026-05-09)

### Intent-Driven Architecture
- ✅ Removed command-driven interface — bot detects intent automatically
- ✅ No `/ask`, `/help`, `/contact` commands needed — just natural conversation
- ✅ Multi-intent router: greeting, discovery, direct_lookup, followup, lead_capture, contact_info
- ✅ HS code discovery mode: 2 clarifying questions → 2-3 code proposals → user picks → XDS query (single turn)
- ✅ Lead capture seamlessly integrated into conversation flow (name → email → phone)
- ✅ Preserved all XDS integration fixes and strict no-hallucination rules

### Key Improvements
1. **Better UX:** Feels like talking to a human consultant, not triggering commands
2. **Discovery Mode:** Helps users find HS codes they don't know (critical feature requested by user)
3. **Intent Detection:** Claude router detects: greeting/discovery/lookup/followup/lead_capture/contact
4. **Per-Chat State:** Rich state structure tracks mode, discovery sub-states, lead capture fields
5. **Simplified Bot:** Removed 150+ lines of scattered state management, single message handler

### Data Flow (Intent-Driven)
```
User Message (natural language)
  ↓
Claude Intent Detector
  ├─ greeting → welcome
  ├─ discovery → ask 2 Qs → propose codes → pick → XDS query
  ├─ direct_lookup → XDS query
  ├─ followup → answer from context
  ├─ lead_capture → collect name/email/phone → Airtable
  └─ contact_info → show contact details
  ↓
RACs Orchestrator (synthesize + CTA)
  ↓
Professional response (no hallucination, single CTA)
```
