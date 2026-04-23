#!/usr/bin/env python3
"""
Monthly Credit Card News Refresh
Uses Gemini Flash models with Google Search grounding.
One API call handles both live research and HTML dashboard generation — no
separate search dependency needed.

Run via GitHub Actions on the 1st of each month, or manually via workflow_dispatch.
Requires: GEMINI_API_KEY environment variable (free at aistudio.google.com)

Resilience strategy (all free-tier):
  1. Try the preferred model with Google Search grounding, retrying on
     transient 429/503 errors with exponential backoff + jitter.
  2. If that model stays unavailable, fall back to other free Gemini models
     that share quota but not capacity pools.
  3. As a last resort, retry without Google Search grounding (ungrounded
     calls are throttled less aggressively) so the dashboard still renders.
  4. If every attempt fails, leave the previous docs/index.html in place and
     exit 0 with a clear warning so GitHub Pages keeps serving the last
     known-good dashboard.
"""

import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types
from google.genai.errors import ServerError, ClientError


# ── CARD PORTFOLIO ────────────────────────────────────────────────
CARDS = [
    # (display name, issuer, annual fee)
    ("Amex Platinum",                "American Express",  695),
    ("Amex Blue Cash Everyday",      "American Express",    0),
    ("Amex Blue Business Plus",      "American Express",    0),
    ("Amex Delta SkyMiles Gold",     "American Express",  150),
    ("Amex Hilton Honors",           "American Express",    0),
    ("Chase Sapphire Preferred",     "Chase",              95),
    ("Chase Freedom Unlimited",      "Chase",               0),
    ("Chase Southwest Priority",     "Chase",             149),
    ("Chase United Explorer",        "Chase",              95),
    ("Chase Ink Business Cash",      "Chase",               0),
    ("Chase Ink Business Unlimited", "Chase",               0),
    ("Capital One Venture X",        "Capital One",       395),
    ("Capital One Venture",          "Capital One",        95),
    ("Discover it Card",             "Discover",            0),
    ("Citi Custom Cash",             "Citi",                0),
    ("Wells Fargo Active Cash",      "Wells Fargo",         0),
    ("US Bank Business Triple Cash", "US Bank",             0),
    ("US Bank Altitude Go",          "US Bank",             0),
]

# ── PROMPT ────────────────────────────────────────────────────────
PROMPT_TEMPLATE = """\
Today is {date}. You are a credit card research assistant generating a monthly \
news dashboard for a cardholder named Dayo. Use Google Search to find the latest \
news, benefit changes, and updates for each of the 18 cards listed below, then \
produce a complete standalone HTML dashboard page.

## Portfolio (18 cards):
{card_list}

## Research Instructions:
For each card, search for and report on:
- Any new benefits, credits, or perks added in the last 60 days
- Benefits removed or reduced
- Annual fee changes
- Changes to earning rates or bonus categories
- New or ended transfer partners / loyalty program tie-ins
- Limited-time promotions or sign-up offers currently active
- Any enrollment or activation required for a benefit (flag these as action items)
- For Discover it: ALWAYS find and prominently display the Q{quarter} {year} \
  5% rotating categories — cardholders must manually activate these each quarter \
  at discover.com/activate

## HTML Dashboard to Generate:
Output a complete, self-contained HTML page. No external CSS or JS dependencies. \
Structure it as follows:

1. HEADER
   - Headline: "💳 Card News & Updates"
   - Subtitle: "{month_year} · 18 cards monitored"
   - Small chip: "Powered by Gemini + Google Search"

2. ⚡ ACTION REQUIRED SECTION (only if applicable)
   Amber/orange banner listing any cards that need the user to do something \
   right now — e.g. "Activate Discover Q{quarter} 5% categories at \
   discover.com/activate" or "Enroll in new Amex benefit by [date]". \
   Make this the most visually prominent element on the page.

3. STATS ROW
   Three chips: "N cards with news" | "N no changes" | "Updated {date}"

4. DISCOVER IT — Q{quarter} {year} SPOTLIGHT
   Always show this section regardless of other Discover news. Display:
   - The specific Q{quarter} 5% rotating categories
   - Maximum cash back: $75 (5% of $1,500 cap)
   - Reminder: must activate by end of Q{quarter} at discover.com/activate
   - Style with Discover orange (#D45600)

5. CHANGES GRID
   Cards that have news — one tile per card. Each tile:
   - Issuer-colored header bar with card name and annual fee
   - One or more badge tags: NEW PERK / BENEFIT CHANGE / FEE CHANGE / \
     PROMO / LIMITED OFFER  (color-coded)
   - 2–5 bullet points of specific findings
   - Source URL cited inline where available
   - "⚠️ Action needed: [what to do]" line if enrollment/activation required

6. NO CHANGES THIS MONTH
   Compact list of cards with no notable news. Collapsible <details> element.

7. FOOTER
   "Researched {month_year} · Auto-refreshed on the 1st of each month \
   via GitHub Actions · {card_count} cards tracked"

## Design Requirements (all inline <style> — no external dependencies):
- Mobile-first, max-width 880px, centered, responsive
- 2-column grid on desktop (≥600px), 1-column on mobile
- Font stack: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif
- Background: #EEF2F7, white card bodies, 12px border-radius, subtle box-shadow
- Issuer color coding for card tile headers:
    Amex        → #1B3A6B (navy)    with gold accent #B8960C
    Chase       → #0A2342 (dark navy)
    Capital One → #1A1A2E (near-black) with purple #4A2C8A
    Discover    → #D45600 (orange)
    Citi        → #003087 (blue)
    Wells Fargo → #8B0000 (dark red)
    US Bank     → #8C1A1A (dark red)
- Badge colors: green=NEW PERK, blue=BENEFIT CHANGE, orange=PROMO, red=FEE CHANGE
- Action Required banner: #FFF7ED background, #D97706 left border (4px), \
  #92400E text
- Stats chips: light gray background, subtle border

## Quality Requirements:
- Use specific details from search results (exact dollar amounts, dates, partner names)
- Cite source URLs inline in bullet points where found
- If search results are thin for a specific card, note "No significant changes \
  found this month" — do not fabricate details
- Every card must appear somewhere (either in Changes or No Changes)

Output ONLY the complete HTML document. Begin with <!DOCTYPE html> and end \
with </html>. Do not include any text outside the HTML tags.\
"""


# ── MAIN ──────────────────────────────────────────────────────────
def main():
    now = datetime.now()
    month_year = now.strftime("%B %Y")
    quarter = (now.month - 1) // 3 + 1
    year = now.year

    print(f"\n{'='*60}")
    print(f"  Monthly Card News Refresh — {month_year}")
    print(f"  Q{quarter} {year}  ·  {len(CARDS)} cards  ·  Gemini Flash")
    print(f"{'='*60}\n")

    # Build card list string for prompt
    card_list = "\n".join(
        f"- {name} ({issuer}, {'$'+str(fee)+'/yr' if fee else 'no annual fee'})"
        for name, issuer, fee in CARDS
    )

    prompt = PROMPT_TEMPLATE.format(
        date=now.strftime("%B %d, %Y"),
        month_year=month_year,
        quarter=quarter,
        year=year,
        card_list=card_list,
        card_count=len(CARDS),
    )

    # ── Call Gemini with model fallback + retry ──────────────────────
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # Free-tier Gemini models, ordered by preference. They share daily quota
    # but live in separate capacity pools, so when one is saturated with a
    # 503 the next usually still serves traffic.
    MODEL_FALLBACKS = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ]

    MAX_RETRIES = 4
    # Base delays in seconds; jitter is added per attempt.
    RETRY_DELAYS = [30, 90, 180, 300]
    RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

    html = None
    last_error = None

    # Outer loop: walk model fallbacks. Inner loop: retry transient errors.
    # On the very last model we also try once more with grounding disabled,
    # since ungrounded calls are throttled far less aggressively.
    for model_idx, model_name in enumerate(MODEL_FALLBACKS):
        is_last_model = model_idx == len(MODEL_FALLBACKS) - 1
        grounding_options = [True, False] if is_last_model else [True]

        for use_grounding in grounding_options:
            mode = "with Google Search" if use_grounding else "WITHOUT grounding (last-resort)"
            print(f"🔍 Trying {model_name} {mode}...")

            tools = (
                [types.Tool(google_search=types.GoogleSearch())]
                if use_grounding
                else None
            )
            config = types.GenerateContentConfig(
                tools=tools,
                temperature=0.2,
                max_output_tokens=16000,
            )

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    print(f"  Attempt {attempt}/{MAX_RETRIES}...")
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=config,
                    )
                    html = response.text.strip()
                    print(f"  ✅ Success with {model_name} ({mode}) — "
                          f"{len(html):,} characters generated")
                    break  # success — exit retry loop

                except (ServerError, ClientError) as e:
                    last_error = e
                    status = (
                        getattr(e, 'status_code', None)
                        or getattr(e, 'code', None)
                    )
                    retryable = status in RETRYABLE_STATUSES
                    if retryable and attempt < MAX_RETRIES:
                        base = RETRY_DELAYS[attempt - 1]
                        # ±20% jitter so concurrent jobs don't sync retries.
                        wait = base * random.uniform(0.8, 1.2)
                        print(f"  ⚠️  {status} error — waiting "
                              f"{wait:.0f}s before retry...")
                        time.sleep(wait)
                    else:
                        # Non-retryable, or out of retries for this
                        # (model, grounding) combo. Break to escalate.
                        print(f"  ✗ Giving up on {model_name} ({mode}): "
                              f"status={status}")
                        break

            if html is not None:
                break  # success — stop trying grounding variants

        if html is not None:
            break  # success — stop trying fallback models

    # ── Handle total failure gracefully ──────────────────────────────
    if html is None:
        print(
            "\n❌ All Gemini models exhausted. Leaving previous "
            "docs/index.html in place so GitHub Pages keeps serving the "
            "last known-good dashboard.",
            file=sys.stderr,
        )
        if last_error is not None:
            print(f"   Last error: {last_error}", file=sys.stderr)
        # Exit 0 so the workflow does not mark the deploy as failed and so
        # the existing dashboard remains published. The next scheduled or
        # manual run will try again.
        return

    # ── Validate output ───────────────────────────────────────────
    if "<!DOCTYPE html>" not in html and "<html" not in html.lower():
        raise RuntimeError(
            "Gemini did not return valid HTML.\n"
            f"First 400 chars:\n{html[:400]}"
        )

    # ── Write dashboard ───────────────────────────────────────────
    docs_dir = Path(__file__).parent.parent / "docs"
    docs_dir.mkdir(exist_ok=True)
    output_path = docs_dir / "index.html"
    output_path.write_text(html, encoding="utf-8")

    size_kb = output_path.stat().st_size / 1024
    print(f"\n✅ Dashboard written → {output_path}  ({size_kb:.1f} KB)")
    print(f"   Live at: https://<your-username>.github.io/<repo-name>/\n")


if __name__ == "__main__":
    main()
