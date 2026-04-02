# pm-bot

an ai portfolio manager that runs on a vps and trades stocks (paper money) autonomously.

## what it does

a python script that wakes up on a cron schedule, gathers market data and news, feeds it through multiple AIs, and executes trades on a paper trading account via alpaca.

the flow:
1. fetches business news from newsapi
2. gpt-4o-mini summarizes the news into bullet points (cheap and fast, grunt work)
3. pulls account info, positions, and 30 days of price data from alpaca
4. claude reads the summaries + prices + its own journal from previous sessions and decides what to trade
5. executes trades on alpaca paper trading
6. saves a journal entry (this is claudes "memory" - it reads it back next time it wakes up)
7. sends a discord notification with the trades and analysis to my phone

claude has no memory between runs. every time the script runs its a fresh api call. the journal files on disk are what give it continuity.

## the schedule

runs on a vps via cron, weekdays only (markets are closed on weekends):

time (ET)  session  what it does
6:00 AM   morning  pre-market analysis, reviews overnight news, plans the day
9:30 AM   market_open   executes any planned trades |
4:00 PM   market_close   end of day review, logs performance |
6:00 PM Sun   weekly   bigger picture thinking, rebalancing, sector rotation

## setup

needs python 3, a vps (or any machine thats always on, a raspberry pi works), and api keys for:
- alpaca (paper trading) - the broker
- anthropic (claude) - the decision maker
- openai (gpt) - the news summarizer
- newsapi - the news source
- discord webhook - notifications

## future ideas

- **multiple competing PMs** - run several with different strategies (aggressive, conservative, momentum, contrarian) on separate paper accounts and see which one wins
- **debating agents** - bull claude argues for buying, bear claude argues against, PM claude makes the final call
- **event-driven triggers** - instead of only running on a schedule, have a cheap script watching prices via websocket that wakes claude up when something big happens (stock drops 5%, unusual volume, etc)
- **news sentiment monitoring** - a cheap model watching a news firehose 24/7 and only pinging claude when something relevant hits
- **better data** - looking for real-time prices, yfinance for fundamentals, SEC filings via gemini (huge context window can eat a 200 page 10-K)
- **self-improving strategy** - claude reviews its own past trades weekly, figures out what worked and what didnt, and rewrites its own strategy.md
- **multi-asset** - stocks + crypto + forex, one PM looking across all of them
- **dashboard** - a web ui showing portfolio performance vs S&P 500, trade history, journal entries
