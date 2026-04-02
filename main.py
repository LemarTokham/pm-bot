# mvp: fetch market data and feed to gpt
# gpt summarises and gives it to claude
# claude will make decisions based on summaries

import config
import json
import sys
import os
import logging
import requests
from openai import OpenAI
from datetime import datetime, timedelta
import anthropic
import alpaca_trade_api as tradeapi

# ── Setup ────────────────────────────────────────────────────────
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    filename=os.path.join(PROJECT_DIR, "pm.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("pm")

gpt = OpenAI(api_key=config.OPENAI_API_KEY)
claude = anthropic.Anthropic(api_key=config.ANTRHOPIC_API_KEY)
alpaca = tradeapi.REST(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, base_url=config.BASE_URL, api_version="v2")


# ── Data Gathering ───────────────────────────────────────────────
def fetch_news():
    try:
        url = f"https://newsapi.org/v2/top-headlines?country=us&category=business&pageSize=10&apiKey={config.NEWS_API_KEY}"
        response = requests.get(url, timeout=10)
        data = response.json()
        articles = data.get("articles", [])
        raw_news = []
        for a in articles:
            title = a.get("title", "")
            description = a.get("description", "")
            raw_news.append(f"{title}\n{description}")
        return "\n\n".join(raw_news)
    except Exception as e:
        log.error(f"News fetch failed: {e}")
        return "News unavailable."


def summarize_news(raw_news):
    try:
        response = gpt.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=500,
            messages=[
                {
                    "role": "system",
                    "content": "You are a financial news analyst. Summarize the following news into 5 concise bullet points that a portfolio manager would care about. Focus on market impact, sector movements, and actionable information."
                },
                {"role": "user", "content": raw_news}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        log.error(f"GPT summarization failed: {e}")
        return "News summary unavailable."


def get_account():
    account = alpaca.get_account()
    return {
        "cash": account.cash,
        "portfolio_value": account.portfolio_value,
        "buying_power": account.buying_power,
    }


def get_positions():
    positions = alpaca.list_positions()
    return [
        {
            "symbol": p.symbol,
            "qty": p.qty,
            "current_price": p.current_price,
            "unrealized_pl": p.unrealized_pl,
        }
        for p in positions
    ]


def get_prices(symbols):
    start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")
    results = {}
    for symbol in symbols:
        try:
            bars = alpaca.get_bars(symbol, "1Day", start=start, end=end, feed="iex").df
            if not bars.empty:
                latest = bars.iloc[-1]
                first = bars.iloc[0]
                results[symbol] = {
                    "price": round(float(latest["close"]), 2),
                    "30d_change": round(((float(latest["close"]) - float(first["close"])) / float(first["close"])) * 100, 2),
                }
        except Exception as e:
            results[symbol] = {"error": str(e)}
    return results


# ── Portfolio State ──────────────────────────────────────────────
def load_portfolio():
    path = os.path.join(PROJECT_DIR, "portfolio.json")
    if os.path.exists(path):
        return json.load(open(path))
    # Default starting state
    return {
        "last_updated": "",
        "watchlist": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "JPM", "JNJ", "XOM", "V", "PG"],
        "trade_history": []
    }


def save_portfolio(portfolio, decision, trade_results):
    portfolio["last_updated"] = datetime.now().isoformat()
    if decision.get("watchlist_updates"):
        portfolio["watchlist"] = decision["watchlist_updates"]
    for result in trade_results:
        portfolio["trade_history"].append({**result, "timestamp": datetime.now().isoformat()})
    path = os.path.join(PROJECT_DIR, "portfolio.json")
    with open(path, "w") as f:
        json.dump(portfolio, f, indent=2)


# ── Memory ───────────────────────────────────────────────────────
def get_recent_journal():
    entries = []
    for i in range(3):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        path = os.path.join(PROJECT_DIR, "journal", f"{date}.md")
        if os.path.exists(path):
            entries.append(open(path).read())
    return "\n".join(entries) if entries else "No previous journal entries."


def save_journal(session_type, decision, trade_results):
    journal_dir = os.path.join(PROJECT_DIR, "journal")
    os.makedirs(journal_dir, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    with open(os.path.join(journal_dir, f"{date}.md"), "a") as f:
        f.write(f"## {session_type.upper()} - {datetime.now().strftime('%H:%M')}\n\n")
        f.write(f"### Analysis\n{decision['analysis']}\n\n")
        f.write(f"### Trades\n{json.dumps(trade_results, indent=2) if trade_results else 'None'}\n\n")
        f.write(f"### Journal\n{decision['journal']}\n\n---\n\n")


# ── Claude Decision ──────────────────────────────────────────────
def ask_claude(session_type, news_summary, account, positions, prices):
    strategy = open(os.path.join(PROJECT_DIR, "strategy.md")).read()
    recent_journal = get_recent_journal()

    prompt = f"""
You are a portfolio manager. This is your {session_type} session.
Today is {datetime.now().strftime("%Y-%m-%d %H:%M")}.

## Your Strategy
{strategy}

## Account
{json.dumps(account, indent=2)}

## Current Positions
{json.dumps(positions, indent=2) if positions else "No positions yet."}

## Price Data
{json.dumps(prices, indent=2)}

## News Summary (prepared by analyst)
{news_summary}

## Recent Journal (your memory)
{recent_journal}

## Instructions
Analyze and respond with ONLY valid JSON:
{{
  "analysis": "brief market analysis",
  "trades": [
    {{"action": "buy", "symbol": "TICKER", "qty": 1, "reason": "why"}}
  ],
  "watchlist_updates": ["TICKER1", "TICKER2"],
  "journal": "your log entry for today"
}}

If no trades needed, return empty trades array.
If watchlist is fine, omit watchlist_updates.
"""

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    if "```" in text:
        text = text.split("```json")[-1].split("```")[0]
    return json.loads(text.strip())


# ── Trade Execution ──────────────────────────────────────────────
def execute_trades(trades):
    results = []
    for trade in trades:
        try:
            alpaca.submit_order(
                symbol=trade["symbol"],
                qty=trade["qty"],
                side=trade["action"],
                type="market",
                time_in_force="day"
            )
            results.append({"symbol": trade["symbol"], "action": trade["action"], "qty": trade["qty"], "status": "submitted", "reason": trade["reason"]})
            print(f"    {trade['action'].upper()} {trade['qty']}x {trade['symbol']} - {trade['reason']}")
        except Exception as e:
            results.append({"symbol": trade["symbol"], "action": trade["action"], "qty": trade["qty"], "status": "failed", "error": str(e)})
            print(f"    FAILED {trade['symbol']}: {e}")
    return results


# ── Main Pipeline ────────────────────────────────────────────────
def run(session_type):
    print(f"\n{'='*50}")
    print(f"  PM Bot - {session_type.upper()}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")
    log.info(f"Starting {session_type} session")

    try:
        # Load state
        portfolio = load_portfolio()

        # Step 1: News
        print("  [1/6] Fetching news...")
        raw = fetch_news()

        # Step 2: Summarize
        print("  [2/6] GPT summarizing...")
        summary = summarize_news(raw)
        print(f"         {summary[:100]}...")

        # Step 3: Market data
        print("  [3/6] Pulling market data...")
        account = get_account()
        positions = get_positions()
        prices = get_prices(portfolio["watchlist"])
        print(f"         Cash: ${account['cash']}  Positions: {len(positions)}")

        # Step 4: Claude decides
        print("  [4/6] Asking Claude...")
        decision = ask_claude(session_type, summary, account, positions, prices)
        print(f"         Analysis: {decision['analysis'][:100]}...")

        # Step 5: Execute
        print("  [5/6] Executing trades...")
        if decision.get("trades"):
            trade_results = execute_trades(decision["trades"])
        else:
            trade_results = []
            print("         No trades.")

        # Step 6: Save
        print("  [6/6] Saving state...")
        save_journal(session_type, decision, trade_results)
        save_portfolio(portfolio, decision, trade_results)

        log.info(f"Session complete. Trades: {len(trade_results)}")
        print(f"\n{'='*50}")
        print(f"  Done! Journal saved.")
        print(f"{'='*50}\n")

    except Exception as e:
        log.error(f"Session failed: {e}")
        print(f"\n  ERROR: {e}")
        print(f"  Check pm.log for details.\n")


if __name__ == "__main__":
    session_type = sys.argv[1] if len(sys.argv) > 1 else "morning"
    run(session_type)
