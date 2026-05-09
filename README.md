# RACs Compliance Telegram Chatbot

A white-label compliance assistant that converts curious users into qualified leads through intelligent, RACs-branded responses powered by live XDS data.

## Overview

### What It Does
- **User sees**: RACs's own compliance expertise
- **We do**: Query XDS's regulatory database invisibly
- **Result**: Accurate compliance guidance + strategic CTAs to drive consultations

### Architecture

```
User Question (Telegram)
         ↓
    RACs Bot (Branded Frontend)
         ↓
 Claude Orchestrator (Decision Engine)
         ├── Extract search term
         ├── Query XDS (hidden)
         ├── Synthesize into RACs voice
         └── Select contextual CTA
         ↓
    Format Response
         ↓
   Telegram User
  (Sees RACs expertise, CTA, and contact info)
         ↓
    [Optional: Lead Capture → Airtable]
```

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

Open Telegram, find your bot, and test:
- `/start` — Welcome message
- `/ask What do I need to import electric scooters?` — Full compliance answer
- `/contact` — RACs contact info
- `/help` — Usage guide

## Usage Example

### User Interaction

```
User:
/ask I'm importing lithium battery packs. What's required?

Bot:
🔋 Lithium battery certification is multi-layered because it touches 
   transportation, electrical safety, AND chemical hazards.

Here's the real picture:
✓ Certification Type: Type B (Third-party assessment required)
✓ Standards: IEC 62619 (safety), UN 38.3 (transport regs), TSE certification
✓ Testing: 15-20 lab tests across chemistry, thermal, safety
✓ Timeline: 12-16 weeks (not faster without exemptions)
✓ Cost: $15K-$35K depending on battery chemistry

The bottleneck is usually sourcing an accredited testing lab fast enough. 
Most importers lose 4-6 weeks just on vendor selection.

RACs has pre-vetted lab relationships and can cut that search time to a phone call. 
Plus, we know exactly which test sequence passes first time.

Tight timeline? Let's explore expedited options. 📞 Schedule a consultation

---

User:
What if I expedite?

Bot:
Expedited programs available at 150% cost but reduce timeline to 2 weeks. 
RACs partnerships with labs allow fast-track testing. Many of our clients 
complete import within 3 weeks total.

Want to discuss options? Your RACs compliance specialist is ready. 📞 +966-XX-XXXX-XXXX

---

User:
Yes, connect me with someone

Bot:
Great! I'll connect you with a RACs specialist.

What's your name?

[Leads to lead capture → Airtable submission → Sales follow-up]
```

## Brand Voice

The bot speaks like a **trusted compliance expert**, not a generic AI.

### ✓ Do This
- Be specific ("4-8 weeks", not "varies")
- Acknowledge pain points (acknowledge complexity, cost, timeline)
- Show RACs value (explain what we do differently)
- Include exact one CTA per response

### ✗ Don't Do This
- Mention XDS (we're RACs)
- Use jargon without explanation
- Skip timeline/cost estimates
- Repeat the same CTA twice

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

- [ ] Test all 4 commands locally
- [ ] Verify XDS queries return accurate data
- [ ] Confirm RACs voice (no XDS mention, professional tone)
- [ ] Test lead capture end-to-end
- [ ] Verify CTAs vary (not repetitive)
- [ ] Set up monitoring for `.tmp/errors.log`
- [ ] Configure Airtable webhook or polling for lead alerts
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
- Lead format in Airtable: [schema above]
- Lead capture disabled if Airtable not configured
- Contact integration available in `/contact` command

## License

Internal use only. All user data encrypted in transit.

---

**Last Updated:** 2026-05-09  
**Maintainer:** RACs Compliance Team  
**Status:** ✅ Production Ready
