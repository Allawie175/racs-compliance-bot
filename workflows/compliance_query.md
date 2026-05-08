# Workflow: Compliance Query Processing

## Objective
Transform a user's compliance question into a RACs-branded response with embedded CTA, powered by XDS data (hidden from user).

## Inputs
- **User Message** (string): Compliance question from Telegram
- **Chat ID** (string): Unique identifier for conversation history
- **Turn Count** (int): Message number in current conversation (1, 2, 3+...)

## Process

### Step 1: Intent Extraction
- **Tool**: Claude (claude-sonnet-4-6)
- **Action**: Parse user message, extract clean search term (1-5 words)
- **Output**: Search term (e.g., "electric scooter", "lithium battery")
- **Fallback**: Return empty string if unable to extract

### Step 2: XDS Query (Hidden)
- **Tool**: XDSQueryEngine.search()
- **Action**: Query XDS API with `?s={term}&p=1`
- **Output**: List of search results (max 10)
- **Data Extracted**:
  - HS code
  - Product name
  - Regulation reference
  - Certification type (Type A, B, C)
  - Applicable standards (ISO, IEC, etc.)
  - Detail page URL
- **Error Handling**: Silent failure → empty list (no error shown to user)
- **Logging**: All errors logged to `.tmp/errors.log` only

### Step 3: Detail Fetch (Optional)
- **Tool**: XDSQueryEngine.get_detail()
- **Action**: Fetch full details from top result's detail page (if URL exists)
- **Output**: Structured detail dict
- **Data Extracted**:
  - Certification procedure steps
  - Required documents
  - Accredited testing bodies
  - Cost estimates (if available)
- **Error Handling**: Silent failure → continue without detail data
- **Performance**: Timeout 10 seconds per request

### Step 4: Voice Synthesis
- **Tool**: Claude (claude-sonnet-4-6)
- **System Prompt**: Brand voice guidelines + response template
- **Input to Claude**:
  - XDS summary (clean, no XDS branding in keys)
  - User's original question
  - Conversation history (last 2 turns for context)
  - Turn count (for CTA selection hint)
- **Claude Task**:
  - Transform XDS data into RACs-branded response
  - Structure: emoji header → summary → bullet requirements → timeline/cost → pain point → RACs value
  - Identify complexity/urgency signals in data
  - Append appropriate CTA (from strategy pool)
- **Output**: Fully formatted response (MarkdownV2 compatible)

### Step 5: CTA Selection
- **Input**: Complexity signals, urgency signals, turn count
- **Logic**:
  - If urgent: pick from `urgent_products` pool
  - Else if complex (multiple standards, Type B/C): pick from `complex_products` pool
  - Else if simple: pick from `simple_products` pool
  - Else if turn ≥3: pick from `returning_user` pool
  - Else if turn == 1: pick from `first_question` pool
  - Else: pick from `default` pool
- **Strategy**: Random selection within category (never same CTA twice per conversation)
- **Source**: `config/cta_strategy.json`

### Step 6: Conversation Memory Update
- **Action**: Store user message + bot response in memory (per chat_id)
- **Retention**: Keep last 6 turns (3 user + 3 bot) per conversation
- **Purpose**: Enable natural follow-up questions with context awareness

## Outputs
- **Response** (string): RACs-branded answer with CTA
- **Format**: Telegram MarkdownV2 compatible
- **Guaranteed**: Every response includes exactly one CTA
- **Time**: <3 seconds from user message to response

## Error Handling

### XDS Query Fails
- **Symptom**: No search results returned
- **Action**: Use fallback response ("I couldn't find specific data...")
- **CTA**: Include default CTA ("Let's talk with an expert")
- **User Sees**: Helpful message without knowing XDS failed

### Claude Synthesis Fails
- **Symptom**: API timeout, rate limit, or invalid response
- **Action**: Use fallback response template
- **CTA**: Always include
- **Logging**: Error logged with full context

### Conversation History Overflow
- **Symptom**: >6 turns in conversation
- **Action**: Keep only last 6 turns in memory (FIFO)
- **Impact**: Older context dropped (acceptable for MVP)

## Edge Cases

### Ambiguous Questions
- Example: "What about batteries?"
- **Handling**: Claude attempts extraction → if empty, ask user for more detail

### Product Not Found
- Example: User asks about product that doesn't exist on XDS
- **Handling**: Return graceful "not found" response + offer consultation

### Multi-Turn Follow-Up
- Example: User asks follow-up without repeating product context
- **Handling**: Conversation history provides context → Claude includes prior answer in synthesis

### Repeat Questions
- Example: User asks same question twice
- **Handling**: Claude notices repeat in history → suggests moving forward with expert consultation

## Rate Limits & Performance

### XDS Rate Limiting
- **Assumed**: 10 requests/second per IP
- **Strategy**: Queue requests, implement exponential backoff
- **Logging**: Track rate-limit hits in `.tmp/errors.log`

### Claude API Rate Limits
- **Model**: claude-sonnet-4-6
- **Assumed**: 50,000 tokens/minute
- **Strategy**: Requests cached where possible (using `cache_control: ephemeral`)
- **Optimization**: System prompt cached across conversation turns

### Response Time SLA
- **Target**: <3 seconds user message → bot response
- **Measured**: XDS (1-2s) + Claude (0.5-1.5s)

## Monitoring & Logging

### Success Metrics
- Queries processed per day
- Average response time
- CTA click rate (tracked in Telegram analytics)
- Conversation length (avg turns per user)

### Error Logging
- File: `.tmp/errors.log`
- Format: timestamp | level | component | error message
- Rotation: Daily (keep 7 days)

### Debugging
- To replay conversation: retrieve chat history from memory
- To test XDS: run `python tools/xds_query.py` standalone
- To test orchestrator: run `python tools/orchestrator.py` with sample query

## Version History

- **v1.0** (2026-05-09): Initial deployment
  - Basic XDS query + Claude synthesis
  - 7 CTA categories
  - In-memory conversation history
  - Airtable lead capture

---

## Future Improvements

### Planned
- [ ] Persistent conversation history (database)
- [ ] Advanced NLP for product classification (faster XDS matching)
- [ ] A/B testing for CTA variations (measure conversion rate)
- [ ] Proactive recommendations ("Based on your questions, you might also need X")

### Research
- [ ] XDS rate-limit optimization (batch API if available)
- [ ] Claude model downgrade path (faster, cheaper synthesis on simple queries)
- [ ] Sentiment analysis (detect frustration, trigger expert call offer)
