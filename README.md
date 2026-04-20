# Economic Dashboard

Self-refreshing macro dashboard for Easton Enterprises. 10 years of monthly data for AU + global markets, commodities, rates, and country debt.

## Live dashboard

**[nickeaston.github.io/economic-dashboard](https://nickeaston.github.io/economic-dashboard/)**

## Refresh schedule

Runs automatically via GitHub Actions at **00:00 UTC on the 1st and 15th** of each month (~10am AEST Melbourne).

## On-demand refresh

Click **"Refresh Now"** on the dashboard (top right) — it opens the GitHub Actions page; hit **"Run workflow"** to trigger an immediate refresh. Takes ~5 min.

## Data sources

- **yfinance** — ASX 200, All Ords, Small Cap, AUD/USD, Dow, NASDAQ, S&P 500, Nikkei, Shanghai, DAX, CAC, FTSE, MSCI EM, Gold, Oil, Copper, Iron Ore
- **IMF PCPS** — Nickel, Lithium, Cobalt
- **ABS Data API** — AU CPI + inflation, unemployment
- **RBA CSV** — cash rate, 2/5/10y bond yields
- **World Bank** — budget balance, private debt, country debt-to-GDP (AU/US/JP/CN/GB/DE/FR)

## Email

Each refresh sends an HTML summary to the configured recipient via SMTP (creds in repo secrets).
