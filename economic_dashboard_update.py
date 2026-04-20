#!/usr/bin/env python3
"""
Economic Dashboard Updater — API Edition
Fetches 10 years of data from free public APIs.
No Google Drive / Excel required.

Sources:
  - yfinance        : market indexes, AUDUSD, Gold, Oil, Copper, Iron Ore (SGX)
  - IMF PCPS        : Nickel, Lithium, Cobalt commodity prices
  - OECD SDMX       : AU cash rate, bond yields, CPI, unemployment
  - World Bank      : budget balance, private debt, country debt-to-GDP

Run on the 1st and 15th of each month (see launchd plist / cron setup below).
"""

import csv, io, json, os, sys, time
from datetime import datetime
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_JSON   = os.path.join(SCRIPT_DIR, "economic_data.json")
GEN_SCRIPT = os.path.join(SCRIPT_DIR, "generate_dashboard.py")

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def ensure_packages(*pkgs):
    import importlib, subprocess
    for pkg in pkgs:
        try:
            importlib.import_module(pkg.split("[")[0])
        except ImportError:
            log(f"  pip install {pkg}...")
            subprocess.run([sys.executable, "-m", "pip", "install", pkg, "-q"])


def fmt_date(dt: datetime) -> str:
    if sys.platform == "darwin":
        return dt.strftime("%-d/%-m/%y")
    return dt.strftime("%d/%m/%y").lstrip("0")


def load_cached() -> dict:
    """Load existing JSON so we can fall back on failed series."""
    if os.path.exists(OUT_JSON):
        with open(OUT_JSON) as f:
            try:
                return json.load(f)
            except Exception:
                pass
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# yfinance
# ─────────────────────────────────────────────────────────────────────────────

def fetch_yf(ticker: str, label: str, unit: str, multiply: float = 1.0) -> dict:
    import yfinance as yf
    log(f"  yfinance  {ticker:20s} → {label}")
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="10y", interval="1wk")
        if hist.empty:
            log(f"    WARNING: empty history for {ticker}")
            return None
        # Sample every 2nd weekly row for ~2 points per month, AND always include
        # the very last row so the chart reflects the most recent data point.
        rows = list(hist.iterrows())
        series = []
        for i, (dt, row) in enumerate(rows):
            if i % 2 == 0 or i == len(rows) - 1:
                v = round(float(row["Close"]) * multiply, 4)
                series.append({"date": fmt_date(dt), "value": v})
        # Today's live close for "current price" display alongside the chart title
        current_price = None
        try:
            today = t.history(period="5d", interval="1d")
            if not today.empty:
                current_price = round(float(today["Close"].iloc[-1]) * multiply, 4)
        except Exception:
            pass
        if current_price is None and series:
            current_price = series[-1]["value"]
        return {"label": label, "unit": unit, "series": series, "current": current_price}
    except Exception as e:
        log(f"    ERROR {ticker}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# IMF Primary Commodity Prices (PCPS) — monthly
# ─────────────────────────────────────────────────────────────────────────────

IMF_BASE = "https://dataservices.imf.org/REST/SDMX_JSON.svc/CompactData/PCPS"

def fetch_imf(code: str, label: str, unit: str, scale: float = 1.0,
              start: str = "2014-01") -> dict:
    """Fetch commodity price from IMF PCPS. Fails fast (12s) to avoid blocking."""
    url = f"{IMF_BASE}/M.W_W.{code}.USD.IX?startPeriod={start}"
    log(f"  IMF PCPS  {code:20s} → {label}")
    try:
        r = requests.get(url, timeout=45, headers=HEADERS)
        r.raise_for_status()
        d = r.json()
        raw = d["CompactData"]["DataSet"]["Series"]
        obs = raw.get("Obs", [])
        if isinstance(obs, dict):
            obs = [obs]
        result = []
        for o in obs:
            tp  = o.get("@TIME_PERIOD", "")
            val = o.get("@OBS_VALUE")
            if not tp or val is None:
                continue
            try:
                y, m = tp.split("-")
                dt = datetime(int(y), int(m), 1)
                result.append({"date": fmt_date(dt),
                               "value": round(float(val) * scale, 4)})
            except Exception:
                continue
        return {"label": label, "unit": unit, "series": result}
    except Exception as e:
        log(f"    IMF {code} unavailable: {e.__class__.__name__}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# ABS (Australian Bureau of Statistics) SDMX API — unemployment, CPI
# ─────────────────────────────────────────────────────────────────────────────

ABS_BASE = "https://api.data.abs.gov.au/data"

def fetch_abs(dataflow: str, key: str, label: str, unit: str,
              scale: float = 1.0, start: str = "2014-01") -> dict:
    """
    Fetch from ABS Data API (free, no key required).
    dataflow: e.g. "LF" or "CPI"
    key:      SDMX dimension key (new API format)
    """
    url = f"{ABS_BASE}/{dataflow}/{key}?startPeriod={start}&format=jsondata"
    log(f"  ABS       {dataflow}/{key[:25]:25s} → {label}")
    try:
        r = requests.get(url, timeout=30, headers=HEADERS)
        r.raise_for_status()
        d = r.json()

        # ABS SDMX-JSON 2.0: structure is at data.structures[0] (not data.structure)
        data_block = d.get("data", {})
        structure = (data_block.get("structure") or
                     (data_block.get("structures") or [{}])[0] or {})
        dims = structure.get("dimensions", {}).get("observation", [])
        time_vals = []
        for dim in dims:
            if dim.get("id") == "TIME_PERIOD":
                time_vals = dim.get("values", [])

        observations = d.get("data", {}).get("dataSets", [{}])[0].get("series", {})
        result = []
        for _, series_val in observations.items():
            for idx_str, obs_data in series_val.get("observations", {}).items():
                idx = int(idx_str)
                if idx >= len(time_vals) or not obs_data or obs_data[0] is None:
                    continue
                tp  = time_vals[idx].get("id", "")
                val = obs_data[0]
                try:
                    if "-Q" in tp:
                        y, q = tp.split("-Q")
                        m = (int(q) - 1) * 3 + 1
                    else:
                        y, m = tp.split("-")
                        m = int(m)
                    dt = datetime(int(y), int(m), 1)
                    result.append({"date": fmt_date(dt),
                                   "value": round(float(val) * scale, 4)})
                except Exception:
                    continue
        result.sort(key=lambda x: x["date"])
        return {"label": label, "unit": unit, "series": result}
    except Exception as e:
        log(f"    ERROR ABS {dataflow}/{key}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# RBA (Reserve Bank of Australia) — cash rate via multiple URL attempts
# ─────────────────────────────────────────────────────────────────────────────

def fetch_rba_csv(table_id: str, series_col: int, label: str, unit: str,
                  scale: float = 1.0, start_year: int = 2014) -> dict:
    """Try several known RBA CSV URL patterns for a given table."""
    slug = table_id.lower().replace(".", "")
    slug_dot = table_id.lower()
    # RBA changed their CSV filename pattern in 2024: now uses "{id}-data.csv"
    candidates = [
        f"https://www.rba.gov.au/statistics/tables/csv/{slug_dot}-data.csv",
        f"https://www.rba.gov.au/statistics/tables/csv/{slug}-data.csv",
        f"https://www.rba.gov.au/statistics/tables/csv/{slug}-hist-data.csv",
        f"https://www.rba.gov.au/statistics/tables/csv/{slug_dot}-hist-data.csv",
        f"https://www.rba.gov.au/statistics/tables/csv/{slug}hist.csv",
    ]
    log(f"  RBA       {table_id:20s} → {label}")
    for url in candidates:
        try:
            r = requests.get(url, timeout=15, headers=HEADERS)
            if r.status_code != 200 or "<html" in r.text[:200].lower():
                continue
            reader = csv.reader(io.StringIO(r.text))
            rows   = list(reader)
            result = []
            for row in rows[11:]:
                if not row or len(row) <= series_col or not row[0].strip():
                    continue
                date_str = row[0].strip()
                val_str  = row[series_col].strip()
                if not val_str or val_str in ("", "..", "N/A"):
                    continue
                dt = None
                # RBA now uses dd/mm/yyyy; also handle legacy formats
                for fmt in ("%d/%m/%Y", "%b-%Y", "%Y-%m-%d", "%d-%b-%Y", "%b %Y"):
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        break
                    except Exception:
                        pass
                if dt is None or dt.year < start_year:
                    continue
                try:
                    v = round(float(val_str.replace(",", "")) * scale, 4)
                    result.append({"date": fmt_date(dt), "value": v})
                except Exception:
                    continue
            if result:
                log(f"    RBA {table_id} → {len(result)} pts from {url.split('/')[-1]}")
                return {"label": label, "unit": unit, "series": result}
        except Exception:
            pass
    log(f"    RBA {table_id} — all URL patterns failed")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# World Bank — macro / debt
# ─────────────────────────────────────────────────────────────────────────────

WB_BASE = "https://api.worldbank.org/v2"

def fetch_wb(country: str, indicator: str, label: str, unit: str,
             start_year: int = 2014) -> dict:
    url = (f"{WB_BASE}/country/{country}/indicator/{indicator}"
           f"?format=json&per_page=500&mrv=500")
    log(f"  World Bank {country}/{indicator[:20]:20s} → {label}")
    try:
        r = requests.get(url, timeout=30, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        if len(data) < 2 or not data[1]:
            return None
        result = []
        for entry in data[1]:
            if entry.get("value") is None:
                continue
            year = int(entry["date"])
            if year < start_year:
                continue
            dt = datetime(year, 12, 31)
            result.append({"date": fmt_date(dt),
                            "value": round(float(entry["value"]), 4)})
        result.sort(key=lambda x: x["date"])
        return {"label": label, "unit": unit, "series": result}
    except Exception as e:
        log(f"    ERROR WB {country}/{indicator}: {e}")
        return None


def fetch_wb_latest(country: str, indicator: str):
    url = (f"{WB_BASE}/country/{country}/indicator/{indicator}"
           f"?format=json&per_page=3&mrv=3")
    try:
        r = requests.get(url, timeout=15, headers=HEADERS)
        d = r.json()
        if len(d) >= 2 and d[1]:
            for entry in d[1]:
                if entry.get("value") is not None:
                    return round(float(entry["value"]), 2)
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# AU Bond Yields — RBA CSV then World Bank fallback
# ─────────────────────────────────────────────────────────────────────────────

def fetch_au_bonds() -> dict:
    """Try RBA F2 table CSV; fall back to World Bank long-term rate."""
    log("  RBA bonds (F2 table)")
    for url in [
        "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv",
        "https://www.rba.gov.au/statistics/tables/csv/f2.1-data.csv",
        "https://www.rba.gov.au/statistics/tables/csv/f2-hist-data.csv",
        "https://www.rba.gov.au/statistics/tables/csv/f2hist.csv",
    ]:
        try:
            r = requests.get(url, timeout=15, headers=HEADERS)
            if r.status_code != 200 or "<html" in r.text[:200].lower():
                continue
            reader = csv.reader(io.StringIO(r.text))
            rows   = list(reader)
            result = []
            for row in rows[11:]:
                if not row or not row[0].strip():
                    continue
                dt = None
                for fmt in ("%d/%m/%Y", "%b-%Y", "%Y-%m-%d", "%d-%b-%Y"):
                    try:
                        dt = datetime.strptime(row[0].strip(), fmt)
                        break
                    except Exception:
                        pass
                if dt is None or dt.year < 2014:
                    continue

                def _col(col, row=row):
                    if len(row) > col and row[col].strip() not in ("", "..", "N/A"):
                        try:
                            return round(float(row[col].strip()), 3)
                        except Exception:
                            pass
                    return None

                entry = {"date": fmt_date(dt), "y2": _col(1), "y5": _col(3), "y10": _col(5)}
                if any(v is not None for v in [entry["y2"], entry["y5"], entry["y10"]]):
                    result.append(entry)
            if result:
                return {"label": "AU Bond Yields", "unit": "%", "series": result}
        except Exception:
            pass

    log("    RBA bonds unavailable — World Bank long-term rate fallback")
    wb = fetch_wb("AU", "FR.INR.LNGR", "AU Bond Yields", "%")
    if wb and wb.get("series"):
        series = [{"date": p["date"], "y2": None, "y5": None, "y10": p["value"]}
                  for p in wb["series"]]
        return {"label": "AU Bond Yields", "unit": "%", "series": series}
    return None


# ─────────────────────────────────────────────────────────────────────────────
# AU CPI + Inflation — ABS then World Bank fallback
# ─────────────────────────────────────────────────────────────────────────────

def fetch_au_cpi() -> dict:
    """ABS Data API for CPI index + YoY inflation (quarterly).

    New ABS SDMX-JSON 2.0 keys (5 dims: MEASURE.INDEX.TSEST.REGION.FREQ):
      CPI index:   1.10001..50.Q  (all-groups index, Australia)
      QoQ change:  2.10001..50.Q  (% change from previous quarter)
    YoY inflation is computed from the index series (current / 4-quarters-ago - 1).
    """
    log("  ABS CPI + inflation (quarterly)")

    cpi_raw = fetch_abs("CPI", "1.10001..50.Q", "CPI Index",      "", start="2014-Q1")

    if not cpi_raw or not cpi_raw.get("series"):
        log("    ABS CPI unavailable — World Bank inflation fallback")
        wb = fetch_wb("AU", "FP.CPI.TOTL.ZG", "Inflation Rate", "%")
        if wb and wb.get("series"):
            series = [{"date": p["date"], "cpi": None, "inflation": p["value"]}
                      for p in wb["series"]]
            return {"label": "CPI & Inflation", "unit": "", "series": series}
        return None

    # Sort CPI index by date string — format is d/m/yy which sorts oddly,
    # so convert to datetime for sorting
    raw_pts = cpi_raw["series"]
    for pt in raw_pts:
        try:
            d, m, y = pt["date"].split("/")
            pt["_dt"] = datetime(2000 + int(y) if int(y) < 100 else int(y), int(m), int(d))
        except Exception:
            pt["_dt"] = datetime(2000, 1, 1)
    raw_pts.sort(key=lambda x: x["_dt"])

    # Detect and normalise base-year rebase (ABS periodically resets index to ~100).
    # If the series has a >15% drop between consecutive points, all earlier points
    # are scaled up so the series is continuous on the new base.
    values = [pt["value"] for pt in raw_pts]
    for i in range(1, len(values)):
        if values[i] is not None and values[i-1] is not None:
            if values[i-1] > 0 and (values[i] / values[i-1]) < 0.85:
                # Rebase discontinuity: estimate old value at new-base start
                # by applying ~0.95% quarterly growth to bridge the gap
                estimated_old = values[i-1] * 1.0095
                norm = values[i] / estimated_old
                for j in range(i):
                    if values[j] is not None:
                        values[j] = round(values[j] * norm, 2)
                log(f"    CPI rebase detected at index {i} — normalised {i} earlier points (factor={norm:.5f})")
                break

    # Interpolate any interior null values in the index
    for i in range(1, len(values) - 1):
        if values[i] is None:
            # Find nearest non-null neighbours
            lo_i = lo_v = hi_i = hi_v = None
            for j in range(i-1, -1, -1):
                if values[j] is not None:
                    lo_i, lo_v = j, values[j]
                    break
            for j in range(i+1, len(values)):
                if values[j] is not None:
                    hi_i, hi_v = j, values[j]
                    break
            if lo_i is not None and hi_i is not None:
                frac = (i - lo_i) / (hi_i - lo_i)
                values[i] = round(lo_v + frac * (hi_v - lo_v), 2)

    # Compute YoY inflation from index (compare to same quarter prior year = 4 steps back)
    series = []
    for i, pt in enumerate(raw_pts):
        v = values[i]
        yoy = None
        if i >= 4 and values[i-4] is not None and values[i-4] != 0:
            yoy = round((v / values[i-4] - 1) * 100, 2) if v is not None else None
        series.append({"date": pt["date"], "cpi": v, "inflation": yoy})

    # Drop trailing entries where inflation is still None (incomplete future quarters)
    while series and series[-1]["inflation"] is None:
        series.pop()

    return {"label": "CPI & Inflation", "unit": "", "series": series}


# ─────────────────────────────────────────────────────────────────────────────
# Country Debt (World Bank) — government + private
# ─────────────────────────────────────────────────────────────────────────────

COUNTRY_MAP = {
    "AU": "Australia",
    "US": "United States",
    "JP": "Japan",
    "CN": "China",
    "GB": "United Kingdom",
    "DE": "Germany",
    "FR": "France",
}
# IMF DataMapper uses ISO3 country codes + GGXWDG_NGDP for Govt Gross Debt % GDP
# (covers all G7/G20 including Japan/China/France where World Bank's
# GC.DOD.TOTL.GD.ZS is empty).
IMF_ISO3 = {
    "AU": "AUS", "US": "USA", "JP": "JPN", "CN": "CHN",
    "GB": "GBR", "DE": "DEU", "FR": "FRA",
}

# IMF WEO 2024 snapshot — authoritative for govt debt/GDP across G7 + AU + CN.
# World Bank's GC.DOD.TOTL.GD.ZS has coverage gaps (empty for JP/CN/FR, stuck in
# 1990 for DE) so we override with these for all 7 countries. Update after each
# IMF WEO release (April + October). Source:
# https://www.imf.org/external/datamapper/api/v1/GGXWDG_NGDP
# Last refreshed manually 2026-04-20.
IMF_WEO_GOVT_DEBT_2024 = {
    "Australia":        49.1,
    "United States":   123.0,
    "Japan":           254.6,
    "China":            93.2,
    "United Kingdom":  101.8,
    "Germany":          62.4,
    "France":          112.2,
}


def fetch_imf_govt_debt() -> dict:
    """IMF DataMapper — comprehensive but sometimes 403s from cloud IPs."""
    from datetime import datetime as _dt
    iso_list = "/".join(IMF_ISO3.values())
    url = f"https://www.imf.org/external/datamapper/api/v1/GGXWDG_NGDP/{iso_list}"
    log("  IMF DataMapper govt debt (GGXWDG_NGDP)")
    try:
        r = requests.get(url, timeout=30, headers=HEADERS)
        r.raise_for_status()
        vals = r.json().get("values", {}).get("GGXWDG_NGDP", {})
        current_year = _dt.now().year
        out = {}
        for iso2, name in COUNTRY_MAP.items():
            years = vals.get(IMF_ISO3[iso2], {})
            actual_years = [int(y) for y in years.keys() if int(y) <= current_year]
            if actual_years:
                y = max(actual_years)
                v = years[str(y)]
                if v is not None:
                    out[name] = round(float(v), 2)
        return out
    except Exception as e:
        log(f"    IMF DataMapper failed: {e} — falling back to WB + WEO snapshot")
        return {}


def fetch_country_debt() -> dict:
    """Govt debt: World Bank for countries that report it + IMF WEO snapshot for
    Japan/China/France (which World Bank doesn't cover). Private debt: World Bank."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    log("  Country debt (World Bank govt + private, parallel)")
    govt    = {}
    private = {}

    def _fetch(iso, name):
        g = fetch_wb_latest(iso, "GC.DOD.TOTL.GD.ZS")
        p = fetch_wb_latest(iso, "FS.AST.PRVT.GD.ZS")
        return name, g, p

    with ThreadPoolExecutor(max_workers=7) as ex:
        futures = {ex.submit(_fetch, iso, name): name
                   for iso, name in COUNTRY_MAP.items()}
        for fut in as_completed(futures):
            try:
                name, g, p = fut.result()
                if g is not None:
                    govt[name] = g
                if p is not None:
                    private[name] = p
            except Exception as e:
                log(f"    country_debt error: {e}")

    # IMF WEO snapshot is authoritative — overrides World Bank since WB has
    # coverage gaps (JP/CN/FR empty) + stale pre-2000 values (DE stuck at 1990).
    # Try the live IMF DataMapper first; if it 403s from GH Actions, fall back
    # to the hardcoded WEO snapshot for ALL countries.
    imf_govt = fetch_imf_govt_debt()
    for name, val in imf_govt.items():
        govt[name] = val

    # Unconditional overlay: IMF WEO snapshot is the authoritative figure for
    # all 7 countries. This overrides any lingering World Bank stale value.
    for name, val in IMF_WEO_GOVT_DEBT_2024.items():
        if name not in imf_govt:   # only override if live IMF didn't provide
            govt[name] = val
            log(f"    {name} govt debt → WEO snapshot ({val}%)")

    return {
        "label":   "Country Debt-to-GDP (%)",
        "govt":    govt,
        "private": private,
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def build_data(cache: dict) -> dict:
    ensure_packages("yfinance", "requests")
    data = {}

    def use(key: str, fetched, label_fallback: str = ""):
        """Store fetched result; fall back to cache if fetch failed or empty.
        Ensures a `current` field is set on every stored series (the most recent
        `value` in the series) — used by the dashboard title row."""
        if fetched and fetched.get("series") and len(fetched["series"]) > 0:
            # For non-yfinance series (IMF/ABS/WB), fetch_* returns no `current` —
            # fall back to the last series value so every series has one.
            if "current" not in fetched or fetched.get("current") is None:
                last_val = fetched["series"][-1].get("value")
                fetched["current"] = last_val
            data[key] = fetched
        elif key in cache:
            log(f"    → using cached data for {key}")
            data[key] = cache[key]
        else:
            data[key] = {"label": label_fallback or key,
                         "unit": "", "series": [], "current": None}

    # ── Australian Markets ──────────────────────────────────────────────────
    log("\n=== Australian Markets ===")
    use("asx200",   fetch_yf("^AXJO",    "ASX S&P 200",   "pts"))
    use("allords",  fetch_yf("^AORD",    "ASX All Ords",  "pts"))
    use("smallcap", fetch_yf("^AXSO",    "ASX Small Cap", "pts"))
    use("audusd",   fetch_yf("AUDUSD=X", "AUD/USD",       ""))

    # ── Australian Economy ──────────────────────────────────────────────────
    log("\n=== Australian Economy ===")

    # Cash rate — try RBA CSV, then World Bank proxy
    use("interest_rate",
        fetch_rba_csv("F1.1", series_col=1, label="RBA Cash Rate", unit="%")
        or fetch_wb("AU", "FR.INR.RINR", "RBA Cash Rate (proxy)", "%"))

    # Unemployment — ABS Labour Force monthly (seasonally adjusted)
    # New ABS SDMX-JSON 2.0 key: MEASURE=M13(Unemp rate), SEX=3(Persons),
    # AGE=1599(Total), TSEST=20(SA), REGION=AUS, FREQ=M
    use("unemployment",
        fetch_abs("LF", "M13.3.1599.20.AUS.M",
                  "Unemployment Rate", "%", start="2014-01"))

    # Bond yields (RBA CSV first, then OECD-style fallback)
    bonds = fetch_au_bonds()
    use("bonds", bonds)

    # CPI & Inflation — ABS quarterly
    # Key: All groups index, Australia, quarterly
    cpi = fetch_au_cpi()
    use("cpi", cpi)

    # Budget balance — World Bank net lending/borrowing % GDP (standard metric, annual)
    # Switched from GC.BAL.CASH.GD.ZS (returns empty since ~2019) on 2026-04-20.
    use("deficit",
        fetch_wb("AU", "GC.NLD.TOTL.GD.ZS",
                 "Budget Balance (Net lending, % GDP)", "%"))

    # Private debt — World Bank (domestic credit to private sector % GDP)
    use("private_debt",
        fetch_wb("AU", "FS.AST.PRVT.GD.ZS",
                 "Private Debt (% GDP)", "%"))

    # ── Commodities ─────────────────────────────────────────────────────────
    log("\n=== Commodities ===")
    use("gold",     fetch_yf("GC=F",  "Gold",          "USD/oz"))
    use("oil",      fetch_yf("CL=F",  "WTI Crude Oil", "USD/bbl"))
    # HG=F is USD/lb — convert to USD/metric ton (1 mt = 2204.62 lb)
    use("copper",   fetch_yf("HG=F",  "Copper",        "USD/t",  multiply=2204.62))
    # TIO=F = SGX TSI Iron Ore 62% Fe CFR China futures (USD/t)
    use("iron_ore", fetch_yf("TIO=F", "Iron Ore",      "USD/t"))
    # Battery/strategic metals — ETF proxies (consistent USD/share across 10y).
    # Prior IMF PCPS feeds (nickel/lithium/cobalt) dropped 2026-04-20 because their
    # historical data had mixed units from multiple API format changes — values
    # jumped between index-points and USD/t across years, producing unusable charts.
    use("lithium",  fetch_yf("LIT",   "Lithium (LIT ETF proxy)",          "USD/share"))
    use("nickel",   fetch_yf("PICK",  "Metals & Mining (PICK ETF proxy)", "USD/share"))
    use("cobalt",   fetch_yf("REMX",  "Strategic Metals (REMX ETF proxy)","USD/share"))

    # ── Global Markets ───────────────────────────────────────────────────────
    log("\n=== Global Markets ===")
    use("dow",      fetch_yf("^DJI",     "Dow Jones",             "pts"))
    use("nasdaq",   fetch_yf("^IXIC",    "NASDAQ",                "pts"))
    use("sp500",    fetch_yf("^GSPC",    "S&P 500",               "pts"))
    use("japan",    fetch_yf("^N225",    "Nikkei 225 (Japan)",    "pts"))
    use("china",    fetch_yf("000001.SS","Shanghai SSE",          "pts"))
    use("dax",      fetch_yf("^GDAXI",   "DAX (Germany)",         "pts"))
    use("cac",      fetch_yf("^FCHI",    "CAC 40 (France)",       "pts"))
    use("ftse",     fetch_yf("^FTSE",    "FTSE 100 (UK)",         "pts"))
    use("emerging", fetch_yf("EEM",      "MSCI Emerging Markets", "pts"))

    # ── Country Debt ─────────────────────────────────────────────────────────
    log("\n=== Country Debt ===")
    cd = fetch_country_debt()
    if cd.get("govt") or cd.get("private"):
        data["country_debt"] = cd
    elif "country_debt" in cache:
        log("    → using cached country_debt")
        data["country_debt"] = cache["country_debt"]
    else:
        data["country_debt"] = {"label": "Country Debt-to-GDP (%)",
                                 "govt": {}, "private": {}}

    # ── Meta ─────────────────────────────────────────────────────────────────
    data["_meta"] = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M AEST"),
        "source":  "APIs: yfinance · OECD · IMF PCPS · World Bank",
        "series":  [k for k in data if not k.startswith("_")],
    }
    return data


def main():
    log("=== Economic Dashboard Updater (API Edition) ===")
    cache = load_cached()
    data  = build_data(cache)

    # Summary
    log("\n=== Series summary ===")
    for k, v in data.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict):
            if "series" in v:
                log(f"  {k:20s}: {len(v['series'])} points")
            elif "govt" in v:
                log(f"  {k:20s}: {len(v.get('govt', {}))} countries")

    with open(OUT_JSON, "w") as f:
        json.dump(data, f, indent=2)
    log(f"\nSaved → {OUT_JSON}")

    # Regenerate HTML
    import subprocess
    result = subprocess.run([sys.executable, GEN_SCRIPT],
                            capture_output=True, text=True, cwd=SCRIPT_DIR)
    if result.returncode == 0:
        log("Dashboard HTML regenerated.")
    else:
        log(f"WARNING: generate_dashboard.py failed:\n{result.stderr[:500]}")


if __name__ == "__main__":
    main()
