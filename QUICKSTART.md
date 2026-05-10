# Quick Start — RACS Compliance Bot

Get your bot running in 10 minutes.

## Step 1: Install Dependencies (2 min)

```bash
cd "Racs telegram"
pip install -r requirements.txt
```

## Step 2: Configure Environment (5 min)

Edit `.env` and fill in:

```bash
# REQUIRED
TELEGRAM_BOT_TOKEN=YOUR_TOKEN_HERE          # Get from @BotFather
ANTHROPIC_API_KEY=YOUR_KEY_HERE             # Get from console.anthropic.com

# REQUIRED (RACS contact info)
RACS_CONTACT_PHONE=+966-50-XXXX-XXXX        # Your phone
RACS_CONTACT_EMAIL=compliance@racs.example  # Your email
RACS_CALENDLY_LINK=https://calendly.com/racs  # Your scheduling link

# OPTIONAL (lead capture)
AIRTABLE_API_KEY=                           # Leave blank to skip
AIRTABLE_BASE_ID=
AIRTABLE_TABLE_NAME=
```

**Getting credentials:**

- **Telegram Token**: Talk to @BotFather on Telegram → `/newbot` → copy token
- **Claude API Key**: Visit [console.anthropic.com](https://console.anthropic.com) → create key
- **Airtable** (optional): [airtable.com/account](https://airtable.com/account) → Personal access tokens

## Step 3: Validate Setup (2 min)

```bash
python validate_setup.py
```

Expected output:
```
✓ .env file exists
✓ TELEGRAM_BOT_TOKEN: configured
✓ ANTHROPIC_API_KEY: configured
... (all checks pass)
✨ All checks passed! Your RACS bot is ready to run.
```

## Step 4: Test Locally (1 min)

```bash
python bot/telegram_bot.py
```

Expected output:
```
🤖 RACS Compliance Bot is running...
Press Ctrl+C to stop.
```

## Step 5: Test in Telegram

Open Telegram, find your bot, and test:

```
/start
```

Expected: Welcome message with RACS branding

```
/ask What do I need to import electric scooters to Saudi Arabia?
```

Expected: Full compliance answer with requirements, timeline, cost, and CTA

```
/contact
```

Expected: Your phone, email, and Calendly link

## Done! 🎉

Your bot is live. Test the full flow:

1. Ask a product question → Get compliance answer
2. Ask follow-up → Bot remembers context
3. After 3+ turns → Bot offers specialist connection
4. Say "yes" → Provide name, email, phone → Lead saved to Airtable

---

## Troubleshooting

**Bot doesn't respond?**
- Check TELEGRAM_BOT_TOKEN is correct (paste from @BotFather)
- Check `.tmp/errors.log` for error details

**Claude API errors?**
- Verify ANTHROPIC_API_KEY is correct
- Check you have credits at [console.anthropic.com](https://console.anthropic.com)

**Airtable not saving leads?**
- Either leave Airtable vars blank (lead capture disabled) or fill all three (base ID, API key, table name)

---

## Next Steps

### For Testing
- Read [README.md](README.md) for full documentation
- See [DEPLOYMENT.md](DEPLOYMENT.md) for production setup

### For Customization
- Brand voice: Edit [brand/racs_voice.md](brand/racs_voice.md)
- CTAs: Edit [config/cta_strategy.json](config/cta_strategy.json)
- Contact info: Edit `.env`

### For Production
- See [DEPLOYMENT.md](DEPLOYMENT.md) for Heroku, Lambda, or VPS setup
- Run full test suite from [DEPLOYMENT.md](DEPLOYMENT.md) pre-deployment checklist

---

**Questions?** Check [README.md](README.md) for detailed docs.
