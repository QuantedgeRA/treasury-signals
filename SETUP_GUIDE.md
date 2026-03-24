# LLM-Powered Intelligence Narratives — Setup Guide

## What This Does

Replaces templated text with Claude-written analyst-quality prose. Every daily briefing now reads like it was written by a Goldman Sachs morning analyst, not a Python template.

Three narrative types:
1. **Daily Intelligence Summary** — replaces the action signal summary
2. **Pattern Explanation** — explains historical patterns in plain English
3. **Purchase Analysis** — contextualizes detected purchases when they happen

---

## Before You Deploy

### 1. Create the narratives table in Supabase

```sql
CREATE TABLE IF NOT EXISTS narratives (
    id BIGSERIAL PRIMARY KEY,
    narrative_type TEXT NOT NULL,
    narrative_date TEXT NOT NULL,
    content TEXT DEFAULT '',
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(narrative_type, narrative_date)
);
```

### 2. Confirm your .env has the API key

In your `treasury-signals/.env`:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### 3. Confirm requirements.txt has anthropic

```
anthropic
```

---

## How to Deploy

### Python scanner (treasury-signals folder):
1. Add `narrative_engine.py` (new file)
2. Replace `main.py`, `email_briefing.py`, `seed_database.py`
3. Run `python main.py`

### Next.js dashboard (treasury-dashboard folder):
1. Extract `treasury-dashboard-v3.tar.gz` into your dashboard folder (replaces existing files)
2. Run `npm run dev`

---

## What You'll See

### Scanner Logs
```
ℹ️  [narrative_engine] Daily narrative generated: 287 chars
ℹ️  [narrative_engine] Pattern explanation generated: 142 chars
ℹ️  [email_briefing] LLM narratives: daily, pattern (429 chars)
```

### Email Briefing
The action signal summary and pattern match section now contain Claude-written prose instead of templated text. If the API is unavailable, it falls back to the original templates.

### Next.js Dashboard
The dashboard loads the latest narrative from Supabase and displays it in the Action Signal card with an "AI-generated analysis" badge.

---

## How It Works

```
Scanner runs → gathers market data, signals, patterns
                    ↓
           narrator.generate_daily_narrative()
                    ↓
           Claude Haiku writes 150-word intelligence brief
                    ↓
           Saved to Supabase 'narratives' table
                    ↓
    Email uses it as action summary
    Dashboard loads it from Supabase
```

### Graceful Fallback
If the Anthropic API key is missing, the package isn't installed, or the API call fails — the system falls back to the original templated text. Nothing breaks. The LLM is purely additive.

### Cost
Claude Haiku at ~$0.25/million input tokens and ~$1.25/million output tokens. Each daily narrative uses roughly 500 input + 200 output tokens. At one briefing per hour, that's about $0.50/month.

---

## Files

### Python (treasury-signals folder)
| File | Status |
|------|--------|
| `narrative_engine.py` | **NEW** — Claude API integration, 3 narrative generators, Supabase storage |
| `main.py` | Updated — imports narrator, generates purchase analyses |
| `email_briefing.py` | Updated — generates daily + pattern narratives, uses in email, longer text limits |
| `seed_database.py` | Updated — narratives table SQL added |

### Next.js (treasury-dashboard folder)
| File | Status |
|------|--------|
| `src/app/dashboard/page.js` | Updated — loads narrative from Supabase, displays with AI badge |
