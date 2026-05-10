# 🔥 viral-meme-agent

Autonomous agent that scrapes viral images, memes, and videos from Nitter and Reddit → analyzes them with **Google Gemini Vision** → generates ready-to-post **English tweets** → notifies you via **Telegram** and/or **Discord** for manual review before posting.

Runs on **GitHub Actions** (free tier), on a configurable schedule.

---

## 🗂 Project Structure

```
viral-meme-agent/
├── .github/
│   └── workflows/
│       └── agent.yml          ← GitHub Actions cron + manual trigger
├── config/
│   └── config.yaml            ← All settings here
├── src/
│   ├── scrapers/
│   │   ├── nitter.py          ← Scrapes Twitter trends via Nitter
│   │   └── reddit.py          ← Scrapes Reddit hot posts
│   ├── media/
│   │   └── downloader.py      ← Downloads images/videos
│   ├── analyzer/
│   │   └── vision.py          ← Gemini Vision analysis
│   ├── generator/
│   │   └── tweet_gen.py       ← Tweet generation
│   ├── notifier/
│   │   ├── telegram_bot.py    ← Telegram notifications
│   │   └── discord_notif.py   ← Discord webhook notifications
│   └── pipeline.py            ← Main orchestrator
├── state/
│   └── seen.json              ← Dedup memory (auto-managed)
├── requirements.txt
└── README.md
```

---

## ⚡ Quick Setup

### 1. Fork / Clone this repo on GitHub

Push the project to a **GitHub repository** (public or private).

### 2. Get your free Gemini API key

Go to → https://aistudio.google.com/app/apikey  
Create a free key. Free tier: **15 requests/min, 1M tokens/day** — more than enough.

### 3. Set up Telegram Bot (optional but recommended)

1. Open Telegram → search `@BotFather`
2. Send `/newbot` → follow prompts → copy the **Bot Token**
3. Start a chat with your bot, then get your **Chat ID**:
   - Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Send any message to your bot first, then refresh the URL
   - Find `"chat":{"id": XXXXXX}` — that's your Chat ID

### 4. Set up Discord Webhook (optional)

1. Go to your Discord server → Settings → Integrations → Webhooks
2. Create a new webhook → choose channel → copy the **Webhook URL**

### 5. Add GitHub Secrets

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Value |
|---|---|
| `GEMINI_API_KEY` | Your Google AI Studio key |
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `DISCORD_WEBHOOK_URL` | Your Discord webhook URL |

> ℹ️ If you don't use Telegram or Discord, set `enabled: false` in `config.yaml` and you can skip those secrets.

### 6. Configure the agent

Edit `config/config.yaml`:

```yaml
agent:
  max_candidates_per_run: 5   # How many tweet candidates to send per run
  min_virality_score: 5       # Only send if Gemini scores >= this (1-10)

scrapers:
  nitter:
    enabled: true   # Set false to disable
  reddit:
    enabled: true   # Set false to disable
    min_score: 1000 # Minimum Reddit upvotes to consider

notifier:
  telegram:
    enabled: true   # Toggle on/off
  discord:
    enabled: true   # Toggle on/off
```

### 7. Set the schedule

Edit `.github/workflows/agent.yml`:

```yaml
- cron: '0 */6 * * *'   # Every 6 hours
```

Common alternatives:
- Every 3 hours: `0 */3 * * *`
- Every 12 hours: `0 */12 * * *`
- Once a day at 9 AM UTC: `0 9 * * *`

---

## 🔄 How It Works

```
GitHub Actions (cron)
       ↓
  Scrape Nitter (trends by region)
  Scrape Reddit (hot meme subreddits)
       ↓
  Download image/video
       ↓
  Gemini Vision — analyze content
  → Description, Humor Type, Virality Score (1-10), Region
       ↓
  Filter (score >= min_virality_score)
       ↓
  Gemini — generate tweet in English
  → Hook + body + 3 hashtags, max 280 chars
       ↓
  Notify via Telegram + Discord
  → Media preview + tweet draft
       ↓
  YOU review → copy tweet + save media → post manually on Twitter/X
```

---

## 📲 What You'll Receive

**Telegram:**
- The image/gif/video as a direct media message
- Caption with: virality score bar, category, region, tweet draft, explanation

**Discord:**
- Embedded card with color-coded virality score
- Image attached
- Tweet draft in a code block (easy to copy)

---

## 🛠 Manual Run

Go to your GitHub repo → **Actions** tab → **viral-meme-agent** → **Run workflow**

---

## 📋 Requirements

- Python 3.11
- Google Gemini API key (free)
- GitHub account (free Actions minutes: 2000 min/month on free tier)

---

## ⚠️ Notes

- **No Twitter/X API used** — you post manually. Zero ban risk.
- Media files are stored as GitHub Actions artifacts for 3 days.
- `state/seen.json` tracks seen posts to avoid duplicates across runs.
- Nitter instances may go down — multiple fallback instances are configured.
