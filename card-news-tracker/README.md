# 💳 Card News Tracker

Automatically researches benefit changes, new perks, and news across an 18-card credit card portfolio every month — outputs a mobile-friendly HTML dashboard hosted on GitHub Pages.

## How it works

1. **GitHub Actions** triggers on the 1st of every month at 9am UTC
2. **`scripts/refresh_cards.py`** runs DuckDuckGo searches for each card's recent news
3. Search results are passed to the **Anthropic Claude API** for synthesis
4. Claude generates a complete **HTML dashboard** with findings, action items, and Discover 5% categories
5. The workflow **commits `docs/index.html`** and pushes — GitHub Pages serves the updated page instantly

You can also trigger a run manually anytime from the Actions tab (→ Run workflow).

---

## One-Time Setup

### 1. Fork / clone this repo
Push to your own GitHub account.

### 2. Add your Anthropic API key as a secret
`Repository → Settings → Secrets & variables → Actions → New repository secret`

| Name | Value |
|------|-------|
| `GEMINI_API_KEY` | your key from AI Studio |

Get your free API key at [aistudio.google.com](https://aistudio.google.com) → Get API key. No credit card required.

### 3. Enable GitHub Pages
`Repository → Settings → Pages`
- Source: **Deploy from a branch**
- Branch: **main** | Folder: **/docs**
- Click **Save**

Your dashboard URL will be:
```
https://<your-username>.github.io/<repo-name>/
```

### 4. Trigger your first run
`Repository → Actions → Monthly Card News Refresh → Run workflow`

Takes about 2 minutes. Bookmark the URL — it auto-refreshes every month.

---

## Cards Tracked (18)

| Issuer | Cards |
|--------|-------|
| American Express | Platinum, Blue Cash Everyday, Blue Business Plus, Delta SkyMiles Gold, Hilton Honors |
| Chase | Sapphire Preferred, Freedom Unlimited, Southwest Priority, United Explorer, Ink Business Cash, Ink Business Unlimited |
| Capital One | Venture X, Venture |
| Discover | Discover it |
| Citi | Custom Cash |
| Wells Fargo | Active Cash |
| US Bank | Business Triple Cash, Altitude Go |

---

## What gets researched each month

- New or removed benefits / credits
- Annual fee changes
- New statement credits or modified amounts
- Limited-time promotions and offers
- Earning rate or redemption value changes
- New transfer partners or loyalty program changes
- Discover it 5% rotating categories for the current quarter (always featured)
- Any benefit that requires immediate action or enrollment

---

## Customizing

**To add or remove a card:** Edit the `CARDS` list at the top of `scripts/refresh_cards.py`.

**To change the run schedule:** Edit `cron:` in `.github/workflows/monthly-card-refresh.yml`.
- Monthly on the 1st: `0 9 1 * *`
- Every Monday: `0 9 * * 1`
- Quarterly: `0 9 1 1,4,7,10 *`

**To change the Claude model:** Edit the `model=` parameter in `refresh_cards.py`. `claude-sonnet-4-6` is the default (good balance of quality and cost). Use `claude-opus-4-6` for maximum research depth.

---

## Cost estimate

Each monthly run makes one Gemini 2.0 Flash API call with Google Search grounding.
**Cost: $0.** Gemini 2.0 Flash is free up to 1,500 requests/day on AI Studio — a
monthly script will never come close to that limit.

---

## Files

```
card-news-tracker/
├── .github/
│   └── workflows/
│       └── monthly-card-refresh.yml   # GitHub Actions schedule
├── scripts/
│   └── refresh_cards.py               # Research + HTML generation script
├── docs/
│   └── index.html                     # Generated dashboard (served by GitHub Pages)
├── requirements.txt
└── README.md
```
