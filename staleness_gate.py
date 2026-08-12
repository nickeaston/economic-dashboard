"""staleness_gate.py — fail loudly when the dashboard refreshes nothing.

WHY THIS EXISTS
---------------
Nick 2026-08-12: "It doesn't look like it's been updating promptly."

The workflow had run flawlessly every three days for months and committed
"Refresh <date>" each time. It was green throughout. Meanwhile t10y2y was frozen
at 5 May, unrate at 1 March, cb_assets at 1 April, and country_debt and eth_burn
held ZERO data points.

Nothing was broken in a way anything could see. The job succeeded, the commit
landed, the page rebuilt — and the numbers on it were months old. A green
workflow that quietly ships stale data is worse than a red one, because it
actively assures you everything is fine.

This gate makes data age a first-class build output.

THRESHOLDS
----------
Series update at genuinely different cadences — a daily equity index and an
annual IMF fiscal series cannot share one limit — so each is judged against the
cadence it actually has. Anything with no data at all is always an error.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

DATA = Path(__file__).parent / 'economic_data.json'

# Per-cadence tolerances, in days. A series is judged against its own class.
DAILY, MONTHLY, QUARTERLY, ANNUAL = 'daily', 'monthly', 'quarterly', 'annual'
TOLERANCE = {DAILY: 10, MONTHLY: 75, QUARTERLY: 200, ANNUAL: 500}

# Some series are as fresh as their SOURCE allows and will never meet the generic
# tolerance. Verified 2026-08-12: AU unemployment reads 2026-05-01 on ABS *and* on
# FRED's OECD mirror (LRHUTTTTAUM156S), so no source on earth has newer — flagging it
# monthly was the gate being wrong, not the data. These carry their own limits, with
# the reason recorded so a future reader can re-test rather than trust a magic number.
SOURCE_LAG_OVERRIDE = {
    'unemployment': (140, 'ABS + OECD/FRED both publish AU labour force ~3 months in arrears'),
    'cpi':          (260, 'ABS quarterly CPI; FRED OECD mirrors are OLDER still (2025-01)'),
    'private_debt': (500, 'World Bank FS.AST.PRVT.GD.ZS is annual and lags 1-2 years'),
    'deficit':      (900, 'World Bank GC.NLD.TOTL.GD.ZS annual; AU last reported 2022'),
}

CADENCE = {
    # market data — should never be more than a few days old
    'asx200': DAILY, 'allords': DAILY, 'smallcap': DAILY, 'audusd': DAILY,
    'bonds': DAILY, 'us_bonds': DAILY, 'gold': DAILY, 'oil': DAILY, 'copper': DAILY,
    'iron_ore': DAILY, 'lithium': DAILY, 'nickel': DAILY, 'cobalt': DAILY,
    'dow': DAILY, 'nasdaq': DAILY, 'sp500': DAILY, 'japan': DAILY, 'china': DAILY,
    'dax': DAILY, 'cac': DAILY, 'ftse': DAILY, 'emerging': DAILY,
    'move_index': DAILY, 'dxy': DAILY, 't10y2y': DAILY, 'tbill_3m': DAILY,
    'stables_mcap': DAILY, 'nft_mcap': DAILY, 'btc_etf_aum': DAILY,
    'eth_etf_aum': DAILY, 'tao_subnet': DAILY, 'crypto_fng': DAILY,
    'truflation': DAILY, 'eth_burn': DAILY, 'strategic_eth': DAILY,
    # official statistics — monthly releases, published in arrears
    'interest_rate': MONTHLY, 'unemployment': MONTHLY, 'unrate': MONTHLY,
    'gscpi': MONTHLY, 'ism_pmi': MONTHLY, 'cb_assets': MONTHLY,
    # quarterly national accounts
    'cpi': QUARTERLY, 'private_debt': QUARTERLY,
    # annual fiscal series
    'deficit': ANNUAL, 'country_debt': ANNUAL,
}

DATE_FORMATS = ('%d/%m/%y', '%d/%m/%Y', '%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y')


def _parse(s) -> datetime.date | None:
    s = str(s).strip()
    for f in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def audit() -> dict:
    data = json.loads(DATA.read_text())
    today = datetime.date.today()
    empty, stale, ok, undated = [], [], [], []

    for key, v in data.items():
        if key.startswith('_') or not isinstance(v, dict):
            continue
        series = v.get('series') or []
        label = v.get('label', key)
        if not series:
            empty.append({'key': key, 'label': label})
            continue
        last = _parse(series[-1].get('date'))
        if last is None:
            undated.append({'key': key, 'label': label, 'raw': series[-1].get('date')})
            continue
        age = (today - last).days
        cad = CADENCE.get(key, MONTHLY)
        tol = TOLERANCE[cad]
        if key in SOURCE_LAG_OVERRIDE:
            tol, _why = SOURCE_LAG_OVERRIDE[key]
            cad = f'{cad} (source-lag)'
        rec = {'key': key, 'label': label, 'last': last.isoformat(),
               'age_days': age, 'cadence': cad, 'tolerance': tol,
               'points': len(series)}
        (stale if age > tol else ok).append(rec)

    return {'total': len(ok) + len(stale) + len(empty) + len(undated),
            'ok': ok, 'stale': stale, 'empty': empty, 'undated': undated,
            'generated': datetime.datetime.now().isoformat(timespec='seconds')}


def main() -> int:
    r = audit()
    print(f"ECONOMIC DASHBOARD STALENESS GATE — {r['total']} series")
    print(f"  fresh {len(r['ok'])} · stale {len(r['stale'])} · "
          f"empty {len(r['empty'])} · undated {len(r['undated'])}\n")

    for e in r['empty']:
        print(f"  EMPTY   {e['key']:16} {e['label']}  — fetcher ran but wrote 0 points")
    for u in r['undated']:
        print(f"  UNDATED {u['key']:16} {u['label']}  — unparseable date {u['raw']!r}")
    for s in sorted(r['stale'], key=lambda x: -x['age_days']):
        print(f"  STALE   {s['key']:16} {s['label'][:32]:34} "
              f"last {s['last']} · {s['age_days']}d old · {s['cadence']} tolerance {s['tolerance']}d")

    bad = len(r['stale']) + len(r['empty']) + len(r['undated'])
    if bad:
        print(f"\n{bad} series need attention. The refresh still committed — this gate reports, "
              f"it does not block a partial update, because fresh data for 39 series is better "
              f"than none. But it must be VISIBLE.")
        return 1
    print("\nAll series within their cadence tolerance.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
