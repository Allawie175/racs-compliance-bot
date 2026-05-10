# Deployment Guide — RACS Compliance Bot

## Pre-Deployment Checklist

### Development Testing
- [ ] Run `python validate_setup.py` (all checks pass)
- [ ] Run `python tools/xds_query.py` (returns results, no errors)
- [ ] Run `python tools/orchestrator.py` (returns RACS-branded response)
- [ ] Run bot locally with `/start`, `/ask`, `/contact`, `/help` commands
- [ ] Test multi-turn conversation (ask follow-up question)
- [ ] Test lead capture flow (respond "yes" to specialist offer)

### Configuration
- [ ] TELEGRAM_BOT_TOKEN obtained from @BotFather
- [ ] ANTHROPIC_API_KEY obtained from Anthropic Console
- [ ] RACS_CONTACT_PHONE formatted correctly
- [ ] RACS_CONTACT_EMAIL set to active mailbox
- [ ] RACS_CALENDLY_LINK points to working scheduling page
- [ ] [Optional] AIRTABLE credentials configured (if using lead capture)

### Brand Verification
- [ ] All responses mention RACS (not generic AI)
- [ ] No mention of XDS in any response
- [ ] CTAs vary (read 5+ responses, check no repeats)
- [ ] Response format consistent (emoji, bullets, timeline, CTA)
- [ ] Professional tone maintained throughout

### Error Handling
- [ ] Tested with invalid product names (graceful fallback)
- [ ] Tested with ambiguous questions (asks for clarification)
- [ ] Tested network disconnection (error logged, user informed)
- [ ] Verified `.tmp/errors.log` captures failures

### Performance
- [ ] Response time <3 seconds (test /ask command)
- [ ] No timeout errors on XDS queries
- [ ] Airtable submission succeeds (<2 seconds)

---

## Local Testing (Before Deployment)

### 1. Full End-to-End Test

```bash
# Terminal 1: Start the bot
python bot/telegram_bot.py

# Terminal 2: In Telegram, test each flow
# Test 1: Simple product
/ask What do I need for a desk lamp?

# Test 2: Complex product
/ask I'm importing lithium batteries

# Test 3: Multi-turn
What's the timeline?
How much does it cost?

# Test 4: Lead capture
[At turn 3+, when bot offers:]
yes
[Provide name, email, phone]
[Verify record appears in Airtable]

# Test 5: Commands
/contact
/help
/start
```

### 2. Error Testing

```bash
# In Telegram, test error scenarios

# Ambiguous question
/ask batteries

# Non-existent product
/ask robot unicorns

# Very long question
/ask What about the comprehensive regulatory framework...
```

Expected: Bot handles gracefully with fallback message.

### 3. Conversation Memory Test

```bash
# Test context awareness

User: /ask I'm importing electric scooters
Bot: [Returns certification requirements]

User: What's the cost?
Bot: [References "scooters" from prior message, no repeat]

User: Can I expedite?
Bot: [Maintains context across 3 turns]
```

---

## Production Deployment

### Option 1: AWS Lambda + API Gateway

**Advantages:** Serverless, auto-scaling, pay-per-use

**Setup:**

```bash
# 1. Create Lambda function
aws lambda create-function \
  --function-name racs-compliance-bot \
  --runtime python3.11 \
  --handler lambda_handler.handler \
  --role arn:aws:iam::YOUR_ROLE

# 2. Upload code
zip -r lambda.zip .
aws lambda update-function-code \
  --function-name racs-compliance-bot \
  --zip-file fileb://lambda.zip

# 3. Create API Gateway webhook
aws apigateway create-rest-api --name racs-bot-api

# 4. Set Telegram webhook
curl -X POST \
  https://api.telegram.org/botTOKEN/setWebhook \
  -d url=https://YOUR_API_GATEWAY_ENDPOINT
```

**Lambda Handler (lambda_handler.py):**

```python
import json
from telegram import Update
from bot.telegram_bot import RACSBot

async def handler(event, context):
    """AWS Lambda handler for Telegram updates"""
    body = json.loads(event["body"])
    update = Update.de_json(body, None)
    
    # Process update with bot
    await RACSBot.handle_update(update)
    
    return {"statusCode": 200, "body": json.dumps({"ok": True})}
```

### Option 2: Heroku

**Advantages:** Simple, free tier available, easy deployments

**Setup:**

```bash
# 1. Create Heroku app
heroku create racs-compliance-bot

# 2. Set environment variables
heroku config:set TELEGRAM_BOT_TOKEN=YOUR_TOKEN
heroku config:set ANTHROPIC_API_KEY=YOUR_KEY
heroku config:set RACS_CONTACT_PHONE=YOUR_PHONE
# ... etc

# 3. Deploy
git push heroku main

# 4. View logs
heroku logs --tail

# 5. Set Telegram webhook
curl -X POST \
  https://api.telegram.org/botTOKEN/setWebhook \
  -d url=https://racs-compliance-bot.herokuapp.com/webhook
```

**Procfile:**

```
web: python bot/telegram_bot.py
```

### Option 3: Self-Hosted VPS

**Advantages:** Full control, can use polling or webhooks

**Setup:**

```bash
# 1. SSH to VPS
ssh user@your-vps.com

# 2. Clone repo
git clone <repo>
cd "Racs telegram"

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create systemd service
sudo nano /etc/systemd/system/racs-bot.service

# Add:
[Unit]
Description=RACS Compliance Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/racs-telegram
Environment="PYTHONUNBUFFERED=1"
ExecStart=/usr/bin/python3 /home/ubuntu/racs-telegram/bot/telegram_bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target

# 5. Enable and start service
sudo systemctl enable racs-bot
sudo systemctl start racs-bot

# 6. View logs
sudo journalctl -u racs-bot -f
```

---

## Post-Deployment Verification

### 1. Bot Responsiveness

```bash
# Test webhook/polling is working
curl https://api.telegram.org/botTOKEN/getMe
# Should return bot info

# Test in Telegram
/start
# Should receive welcome message
```

### 2. Conversation Flow

```bash
# Send test message via Telegram
/ask I'm importing wireless earbuds

# Expected:
# - Response within 3 seconds
# - Mentions wireless earbuds
# - Includes certification requirements
# - Includes one CTA
# - No XDS mention
```

### 3. Lead Capture

```bash
# After 3+ turns, respond "yes"
# Provide name, email, phone
# Check Airtable table for new record
```

### 4. Error Logging

```bash
# SSH to deployment
tail -f .tmp/errors.log

# Should show only genuine errors:
# - XDS timeouts
# - Claude API rate limits
# - Airtable submission failures
# (NOT normal queries)
```

### 5. Performance Monitoring

Set up alerts for:
- Response time >3 seconds
- Error rate >1%
- Airtable submission failures
- XDS connection issues

---

## Monitoring & Maintenance

### Daily
- [ ] Check `.tmp/errors.log` for new failures
- [ ] Monitor Airtable leads (count, quality)
- [ ] Test one /ask command to verify bot is up

### Weekly
- [ ] Review conversation patterns (new pain points)
- [ ] Check CTA performance (which CTAs drive clicks?)
- [ ] Update brand voice if needed

### Monthly
- [ ] Review Airtable leads → closed deals conversion
- [ ] Analyze XDS queries (which products asked most?)
- [ ] Update workflows doc with new discoveries
- [ ] Rotate API keys (best practice)

### Quarterly
- [ ] Review bot performance metrics
- [ ] Audit RACS voice consistency
- [ ] Plan next improvements (Phase 2 roadmap)

---

## Rollback Plan

If something goes wrong in production:

```bash
# Option 1: Revert to previous version
git revert <commit>
git push heroku main  # or redeploy to Lambda/VPS

# Option 2: Disable bot temporarily
curl -X POST \
  https://api.telegram.org/botTOKEN/setWebhook \
  -d url=  # empty URL disables webhook

# Option 3: Switch to polling (slower but more reliable)
# Edit bot/telegram_bot.py: change from webhook to polling
python bot/telegram_bot.py  # restart

# Option 4: Manual lead handling
# If Airtable is down, leads are logged locally
# Manually sync from .tmp/pending_leads.json to Airtable later
```

---

## Troubleshooting

### Bot Not Responding
1. Check TELEGRAM_BOT_TOKEN is correct
2. Verify webhook URL is working: `curl https://your-webhook-url`
3. Check logs: `.tmp/errors.log`
4. Restart bot service: `systemctl restart racs-bot`

### XDS Queries Failing
1. Verify `XDS_BASE_URL` is reachable: `curl https://xds.com.sa`
2. Check network connectivity
3. Review rate limits (10 req/sec)
4. Check `.tmp/errors.log` for error details

### Claude API Errors
1. Verify ANTHROPIC_API_KEY is correct
2. Check API rate limits (50K tokens/min)
3. Verify account has credits
4. Check Claude API status page

### Airtable Lead Submission Failing
1. Verify AIRTABLE_API_KEY is correct
2. Verify BASE_ID and TABLE_NAME match
3. Check table schema (must have: Name, Email, Phone, Product Interest)
4. Check Airtable API limits (5 req/sec)

---

## Scaling Considerations

### Current Capacity
- Handles ~100 concurrent users
- ~10 requests/second sustained
- ~100 leads/day typical

### If Growing Beyond Capacity

1. **Switch from polling to webhooks** (faster, fewer API calls)
2. **Add conversation caching** (reduce Claude calls)
3. **Database for history** (currently in-memory only)
4. **Load balancing** (multiple bot instances)
5. **Dedicated Airtable sync** (decouple from main bot)

---

## Success Metrics (First 30 Days)

| Metric | Target | Tool |
|---|---|---|
| Daily Active Users | 50+ | Telegram Analytics |
| Avg Conversation Length | 2.5+ turns | Bot logs |
| Lead Submission Rate | 10%+ of users | Airtable |
| Response Time | <3 sec | Bot logs |
| Error Rate | <1% | .tmp/errors.log |
| CTA Click Rate | 15%+ | Telegram Analytics |

---

**Deployment Date:** __________  
**Deployed By:** __________  
**Status:** ☐ Development ☐ Staging ☐ Production
