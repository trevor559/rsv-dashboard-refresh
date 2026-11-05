"""Home summary for the dashboard (dataset home_pack).

Same results as the page's calcs home_alerts, notes_sales, notes_customers, notes_team, sales_stats, sales_trend,
smoke_stats, at_risk_stats, discount_watch_stats and home_returns (and the calcs they use), worked out ahead of time
so the home screen doesn't download ~10 MB. Output rows: {calc, state, region, row (the calc row as JSON text)}.

Written to match the page's JavaScript exactly: Math.round rounding, left-to-right float sums, stable sorts,
and JavaScript number formatting in the note text.
"""
import datetime, json, math

INPUTS = ['at_risk', 'at_risk_stores', 'basket_pairs', 'code_reuse', 'customer_mix', 'discount_watch', 'discounts',
          'returns_defects', 'returns_variants', 'sales_monthly', 'second_visit', 'smoke_store_groups', 'stores',
          'store_sales', 'team_scorecard', 'top_products', 'traffic_hours', 'weekly_sales', 'winback', 'winback_stores']
PACK_CALCS = ['home_alerts', 'notes_sales', 'notes_customers', 'notes_team', 'sales_stats', 'sales_trend', 'smoke_stats',
              'at_risk_stats', 'discount_watch_stats', 'home_returns']
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
WB_SEGS = ['12+ months away', '6–12 months away', 'Under 6 months away', 'No earlier visit on file']
TRAFFIC_WEEKS = 8
NUL = object()  # JavaScript undefined


# ---------------------------------------------------------------- JavaScript semantics
def jround(x):
    return math.floor(x + 0.5)


def jsum(values, start=0):
    t = start
    for v in values:
        t = t + v
    return t


def jnum(v):
    """String(number) in JavaScript."""
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return 'NaN'
        if math.isinf(v):
            return 'Infinity' if v > 0 else '-Infinity'
        if v.is_integer() and abs(v) < 1e21:
            return str(int(v))
        r = repr(v)
        if 'e' in r:  # JavaScript writes 1e-7 / 1e+21
            m, e = r.split('e'); e = int(e)
            return m + 'e' + ('+' if e > 0 else '-') + str(abs(e))
        return r
    return str(v)


def loc(v):
    """Math.round(v).toLocaleString('en-US')."""
    return '{:,}'.format(int(jround(v)))


def money(v):
    return '$' + loc(v)


def pct_change(a, b):
    return jround((a / b - 1) * 1000) / 10 if b else None


def sign(v):
    if v is None:
        return '—'
    return ('+' if v > 0 else '−' if v < 0 else '') + jnum(abs(v)) + '%'


def nlist(a):
    return ''.join(a) if len(a) <= 1 else ', '.join(a[:-1]) + ' and ' + a[-1]


def nmon(iso):
    d = datetime.date.fromisoformat(iso)
    return d.strftime('%b') + ' ' + str(d.day)


def nmonth(m):
    return MONTHS[int(str(m)[5:7]) - 1] + ' ' + str(m)[:4]


def hour_label(h):
    return str(h % 12 or 12) + ('am' if h < 12 else 'pm')


def g(r, k, default=0):
    """r[k] || default"""
    v = r.get(k)
    return v if v else default


def truthy(v):
    return bool(v) and not (isinstance(v, float) and math.isnan(v))


def to_json(v):
    """JSON.stringify output."""
    def clean(x):
        if isinstance(x, bool) or x is None or isinstance(x, str):
            return x
        if isinstance(x, float):
            if not math.isfinite(x):
                return None
            if x == 0:
                return 0
            return int(x) if x.is_integer() and abs(x) < 2 ** 53 else x
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items() if v is not NUL}
        if isinstance(x, list):
            return [clean(v) for v in x]
        return x
    return json.dumps(clean(v), ensure_ascii=False, separators=(',', ':'))


def uniq(seq):
    return list(dict.fromkeys(seq))


def nrow(tab, area, s, gg, note, priority, action=False):
    return {'id': '|'.join([s, gg, tab]), 'state': s, 'region': gg, 'tab': tab, 'area': area, 'note': note, 'priority': priority, 'action': bool(action)}


def nscopes(stores):
    out = [('ALL', 'All')]
    for st in uniq(s['state'] for s in stores):
        out.append((st, 'All'))
        for reg in uniq(s['region'] for s in stores if s['state'] == st):
            out.append((st, reg))
    return out


def nin(r, s, gg):
    return (s == 'ALL' or r.get('state') == s) and (gg == 'All' or r.get('region') == gg)


def scope_stats(rows, fn):
    out = []
    for state in uniq(r.get('state') for r in rows):
        regions = ['All'] + uniq(r.get('region') for r in rows if r.get('state') == state)
        for region in regions:
            out.append(dict({'state': state, 'region': region}, **fn([r for r in rows if r.get('state') == state and (region == 'All' or r.get('region') == region)])))
    if rows:
        out.append(dict({'state': 'ALL', 'region': 'All'}, **fn(rows)))
    return out


def sum_states(rows, key_of, init, num_re):
    import re
    out = {}
    for r in rows:
        if r.get('region') != 'All':
            continue
        k = key_of(r)
        if k not in out:
            out[k] = dict({'state': 'ALL', 'region': 'All'}, **init(r))
        o = out[k]
        for f, v in r.items():
            if re.match(num_re, f) and isinstance(v, (int, float)) and not isinstance(v, bool):
                o[f] = (o.get(f) or 0) + v
    return list(out.values())


def full_months(monthly):
    return sorted(uniq(m['month'] for m in monthly if not m.get('partial')))


def last_full_key(monthly):
    return full_months(monthly)[-1].replace('-', '_', 1)


# ---------------------------------------------------------------- calcs
def at_risk_stats(stores_rows, risk):
    def fn(r):
        names = {x['store'] for x in r}
        reg = jsum(x['regulars'] for x in r); ar = jsum(x['at_risk'] for x in r)
        return {'regulars': reg, 'at_risk': ar, 'at_risk_pct': jround(ar / reg * 1000) / 10 if reg else None,
                'spend_at_risk': jround(jsum(x['spend_90d'] for x in risk if x['store'] in names))}
    return scope_stats(stores_rows, fn)


def discount_watch_stats(dw, cr):
    a = scope_stats(dw, lambda r: {'reviewed': len(r), 'flagged': len([x for x in r if (x.get('flag_count') or 0) > 0])})
    b = scope_stats(cr, lambda r: {'code_reuse': len(r)})
    out = []
    for x in a:
        y = next((y for y in b if y['state'] == x['state'] and y['region'] == x['region']), {})
        out.append(dict(x, code_reuse=y.get('code_reuse') or 0))
    return out


def wb_scopes(rows):
    out = {}
    for r in rows:
        for s, gg in ((r.get('state'), 'All'), (r.get('state'), r.get('region')), ('ALL', 'All')):
            if not s:
                continue
            out.setdefault(str(r['campaign']) + '|' + str(s) + '|' + str(gg), []).append(r)
    return out


def wb_pct(a, b):
    return jround(a / b * 1000) / 10 if b else None


def js_sorted_str(vals):
    """[...].sort() in JavaScript: compares as strings, keeps the original values, undefined last."""
    vals = list(vals)
    return sorted(vals, key=lambda v: 'null' if v is None else str(v))


def winback_stats(wb, st):
    a, b = wb_scopes(wb), wb_scopes(st)
    out = []
    for k in uniq(list(a) + list(b)):
        campaign, state, region = k.split('|')
        c, s = a.get(k, []), b.get(k, [])
        red = jsum(x['redemptions'] for x in s); trk = jsum(x['tracked'] for x in s)
        lapsed = len([x for x in c if x.get('segment') == WB_SEGS[0]]); back = len([x for x in c if (x.get('return_visits') or 0) > 0])
        reg = len([x for x in c if (x.get('return_visits_90d') or 0) >= 3])
        fd = js_sorted_str(x.get('first_day') for x in s); ld = js_sorted_str(x.get('last_day') for x in s)
        out.append({'campaign': campaign, 'state': state, 'region': region, 'redemptions': red, 'tracked': trk, 'tracked_pct': wb_pct(trk, red),
                    'customers': len(c), 'lapsed': lapsed, 'lapsed_pct': wb_pct(lapsed, len(c)), 'came_back': back, 'came_back_pct': wb_pct(back, len(c)),
                    'regulars': reg, 'sales_after': jround(jsum(x['sales_after'] for x in c)), 'discount_total': jround(jsum(x['discount_total'] for x in s)),
                    'recent_pct': wb_pct(len([x for x in c if x.get('segment') == WB_SEGS[2]]), len(c)),
                    'first_day': (fd[0] if fd and fd[0] else None), 'last_day': (ld[-1] if ld and ld[-1] else None)})
    return out


def sales_stats(store_sales, monthly):
    full_m = full_months(monthly)

    def fn(r):
        names = {x['store'] for x in r}
        full = {x['store'] for x in r if x.get('trend_pct') is not None}

        def sum_f(ms):
            return jsum(m['net_sales'] for m in monthly if m['store'] in full and m['month'] in ms)
        q3 = sum_f(full_m[-3:]); q2 = sum_f(full_m[-6:-3])
        sales = jsum(x['sales_last_month'] for x in r); orders = jsum(x['orders_last_month'] for x in r)
        lw = [x for x in r if x.get('loyalty_share') is not None]
        lm = full_m[-1]; pm = full_m[-2] if len(full_m) >= 2 else None; ly = str(int(lm[:4]) - 1) + lm[4:]

        def by(m):
            o = {}
            for x in monthly:
                if x['store'] in names and x['month'] == m:
                    o[x['store']] = x['net_sales']
            return o
        cur, prv, old = by(lm), by(pm), by(ly)

        def tot(mp):
            return jsum(mp.values())
        same = [s for s in cur if (old.get(s) or 0) > 0]
        ss_c = jsum(cur[s] for s in same); ss_o = jsum(old[s] for s in same)
        lw_orders = jsum(x['orders_last_month'] for x in lw)
        return {'stores': len(r), 'sales_last_month': jround(sales), 'orders_last_month': orders,
                'aov': jround(sales / orders * 100) / 100 if orders else None,
                'mom_pct': pct_change(tot(cur), tot(prv)), 'yoy_pct': pct_change(tot(cur), tot(old)) if old else None,
                'same_store_yoy_pct': pct_change(ss_c, ss_o) if same else None, 'same_stores': len(same), 'last_year_month': ly,
                'trend_pct': jround((q3 / q2 - 1) * 1000) / 10 if q2 else None,
                'loyalty_share': (jround(jsum(x['loyalty_share'] * x['orders_last_month'] for x in lw) / lw_orders * 10) / 10 if lw_orders else None) if lw else None}
    return scope_stats(store_sales, fn)


def customer_monthly(rows):
    F = ['orders', 'net_sales', 'new_customers', 'new_orders', 'returning_orders', 'loyalty_orders', 'loyalty_sales', 'new_joined_loyalty',
         'cohort_new', 'cohort_came_back', 'rewards_redeemed', 'reward_dollars', 'points_redeemed', 'points_earned_est']
    out = {}
    for r in rows:
        for s, gg in ((r['state'], 'All'), (r['state'], r['region']), ('ALL', 'All')):
            k = str(s) + '|' + str(gg) + '|' + str(r['month'])
            if k not in out:
                out[k] = dict({'state': s, 'region': gg, 'month': r['month'], 'partial': r.get('partial')}, **{f: 0 for f in F})
            o = out[k]
            for f in F:
                o[f] = o[f] + g(r, f)

    def p(a, b):
        return jround(a / b * 1000) / 10 if b else None
    return [dict(o, second_visit_pct=p(o['cohort_came_back'], o['cohort_new']) if o['cohort_new'] else None) for o in out.values()]


def sum_problems(rows, key_of, init):
    rs = sum_states(rows, key_of, init, r'^(units_sold|returns|return_amt|defect_replacements|defect_amt)$')
    rs = [dict(r, problem_rate_pct=jround((r['returns'] + r['defect_replacements']) / r['units_sold'] * 1000) / 10 if r.get('units_sold') else None) for r in rs]
    rs = sorted(rs, key=lambda r: -(r['returns'] + r['defect_replacements']))
    return [dict(r, rank=i + 1) for i, r in enumerate(rs)]


def home_alerts(returns_variants, ar_stats, dw_stats, wb_stats, s_stats, cm, rv_all):
    scopes = {}
    for rs in (s_stats, ar_stats, dw_stats):
        for r in rs:
            if not r.get('store'):
                scopes.setdefault(str(r['state']) + '|' + str(r['region']), (r['state'], r['region']))
    out = []
    for state, region in scopes.values():
        def one(rs):
            return next((r for r in rs if r['state'] == state and r['region'] == region and not r.get('store')), None)
        n = [0]

        def add(key, level, area, tab, headline, detail):
            out.append({'state': state, 'region': region, 'key': key, 'level': level, 'area': area, 'tab': tab, 'headline': headline, 'detail': detail, 'sort': n[0]}); n[0] += 1
        cand = [r for r in returns_variants + rv_all if r.get('state') == state and r.get('region') == region and r['units_sold'] >= 50 and (r.get('problem_rate_pct') or 0) > 3]
        for r in sorted(cand, key=lambda r: -r['problem_rate_pct'])[:3]:
            add('defect|' + r['item'] + '|' + r['variation'], 'act', 'Product quality', 'returns', r['item'] + ' – ' + r['variation'] + ': ' + jnum(r['problem_rate_pct']) + '% came back',
                loc(r['returns']) + ' returned and ' + loc(r['defect_replacements']) + ' swapped as defective, of ' + loc(r['units_sold']) + ' sold in 90 days. Raise it with the supplier.')
        ar = one(ar_stats)
        if ar and ar['at_risk']:
            add('atrisk', 'act' if ar['at_risk_pct'] >= 15 else 'watch', 'Customers', 'atrisk', loc(ar['at_risk']) + ' regulars haven’t been back in 30+ days',
                jnum(ar['at_risk_pct']) + '% of regulars, who spent ' + money(ar['spend_at_risk']) + ' in the 90 days before.')
        dw = one(dw_stats)
        if dw and dw['flagged']:
            add('discwatch', 'watch', 'Loss prevention', 'abuse', loc(dw['flagged']) + ' team members flagged for unusual discounts', 'Of ' + loc(dw['reviewed']) + ' reviewed over the last 30 days. A reason to look, not proof.')
        if dw and dw['code_reuse']:
            add('codereuse', 'watch', 'Loss prevention', 'reuse', loc(dw['code_reuse']) + ' customers used a one-time code more than once', 'Set campaign codes to one use per customer in Square.')
        ss = one(s_stats)
        if ss and ss['same_store_yoy_pct'] is not None:
            v = ss['same_store_yoy_pct']
            add('yoy', 'watch' if v < 0 else 'info', 'Sales', 'sales', 'Same-store sales ' + ('down ' if v < 0 else 'up ') + jnum(abs(v)) + '% vs last year',
                'Latest full month vs the same month a year ago, ' + loc(ss['same_stores']) + ' stores open both months' +
                ('; all stores including new ones: ' + ('+' if ss['yoy_pct'] > 0 else '') + jnum(ss['yoy_pct']) + '%.' if ss['yoy_pct'] is not None else '.'))
        if ss and ss['trend_pct'] is not None:
            v = ss['trend_pct']
            add('trend', 'watch' if v < 0 else 'info', 'Sales', 'sales', 'Net sales ' + ('down ' if v < 0 else 'up ') + jnum(abs(v)) + '%', 'Last 3 full months vs the 3 before, stores open all six months.')
        wbs = [w for w in wb_stats if w['state'] == state and w['region'] == region and w['customers']]
        for w in _sort_desc_str(wbs, 'first_day'):
            add('wb|' + w['campaign'], 'info', 'Win-back', 'winback', w['campaign'] + ': ' + loc(w['came_back']) + ' of ' + loc(w['customers']) + ' came back',
                loc(w['regulars']) + ' are regulars again. ' + money(w['sales_after']) + ' in return-visit sales vs ' + money(w['discount_total']) + ' discounted.')
        cms = [m for m in cm if m['state'] == state and m['region'] == region and m['second_visit_pct'] is not None]
        if cms:
            c = _sort_desc_str(cms, 'month')[0]
            add('cohort', 'info', 'Customers', 'custmix', jnum(c['second_visit_pct']) + '% of ' + MONTHS[int(c['month'][5:7]) - 1] + '’s first-time customers came back',
                loc(c['cohort_came_back']) + ' of ' + loc(c['cohort_new']) + ' placed a second order since.')
    return out


def _sort_desc_str(rows, key):
    """Stable sort by String(row[key]) descending (b.localeCompare(a))."""
    import functools

    def cmp(a, b):
        x = 'null' if b.get(key) is None else str(b.get(key)); y = 'null' if a.get(key) is None else str(a.get(key))
        return (x > y) - (x < y)
    return sorted(rows, key=functools.cmp_to_key(cmp))


def weekly_scope(weekly):
    out = {}
    for r in weekly:
        for s, gg in ((r['state'], 'All'), (r['state'], r['region']), ('ALL', 'All')):
            k = '|'.join([str(s), str(gg), r['week']])
            if k not in out:
                out[k] = {'state': s, 'region': gg, 'week': r['week'], 'week_end': r.get('week_end'), 'net_sales': 0, 'orders': 0, 'same_now': 0, 'ly_same': 0}
            o = out[k]; o['net_sales'] += r['net_sales']; o['orders'] += r['orders']
            if (r.get('ly_net_sales') or 0) > 0 and r['net_sales'] > 0:
                o['same_now'] += r['net_sales']; o['ly_same'] += r['ly_net_sales']
    return [dict(o, net_sales=jround(o['net_sales']), same_now=jround(o['same_now']), ly_same=jround(o['ly_same']), yoy_pct=pct_change(o['same_now'], o['ly_same'])) for o in out.values()]


def weekly_store_table(weekly):
    weeks = sorted(uniq(r['week'] for r in weekly))
    w4, w3, w2, w1 = ([None] * 4 + weeks)[-4:]
    by = {}
    for r in weekly:
        by.setdefault(r['store'], {})[r['week']] = r
    out = []
    for store, w in by.items():
        last = w.get(w1) or {}; prev = w.get(w2) or {}
        four = [w[x] for x in (w4, w3, w2, w1) if x in w]
        anyr = next(iter(w.values()))
        n4 = jsum(r['net_sales'] for r in four)
        ly4 = jsum(r['ly_net_sales'] for r in four) if len(four) == 4 and all((r.get('ly_net_sales') or 0) > 0 for r in four) else 0
        lns = last.get('net_sales') or 0; lly = last.get('ly_net_sales')
        out.append({'store': store, 'state': anyr['state'], 'region': anyr['region'], 'week': w1, 'last_week': jround(lns), 'prev_week': jround(prev.get('net_sales') or 0),
                    'wow_pct': pct_change(lns, prev.get('net_sales') or 0), 'ly_week': jround(lly) if lly else None,
                    'yoy_pct': pct_change(last.get('net_sales'), lly) if (lly or 0) > 0 else None,
                    'avg_4wk': jround(n4 / (len(four) or 1)), 'yoy_4wk_pct': pct_change(n4, ly4) if ly4 else None})
    return out


def discounts_all(discounts, monthly):
    lk = 'amt' + last_full_key(monthly)
    rows = sum_states(discounts, lambda r: r['discount'], lambda r: {'discount': r['discount'], 'type': r.get('type'), 'group': r.get('group'), 'flag': ''},
                      r'^((uses|orders|amt)\d{4}_\d{2}|stores_using)$')
    rows = sorted(rows, key=lambda r: -(r.get(lk) or 0))
    return [dict(r, rank=i + 1) for i, r in enumerate(rows)]


def discount_stats(discounts, monthly, d_all):
    disc = discounts + d_all
    full = full_months(monthly); last = full[-1]; sfx = last.replace('-', '_', 1)
    out = []
    for key in uniq(str(d['state']) + '|' + str(d['region']) for d in disc):
        state, region = key.split('|')
        ds = [d for d in disc if str(d['state']) == state and str(d['region']) == region]
        amt = jsum(g(d, 'amt' + sfx) for d in ds); orders = jsum(g(d, 'orders' + sfx) for d in ds)
        sales = jsum(m['net_sales'] for m in monthly if (state == 'ALL' or m['state'] == state) and (region == 'All' or m['region'] == region) and m['month'] == last)
        top = sorted(ds, key=lambda d: -g(d, 'amt' + sfx))[0] if ds else None
        out.append({'state': state, 'region': region, 'amount': jround(amt), 'orders': orders,
                    'pct_of_sales': jround(amt / sales * 1000) / 10 if sales else None, 'top_discount': top['discount'] if top else None})
    return out


def traffic_stats(rows):
    keys = {}
    for r in rows:
        for k in (('ALL', 'All', ''), (r['state'], 'All', ''), (r['state'], r['region'], ''), (r['state'], r['region'], r['store'])):
            keys.setdefault('|'.join(str(x) for x in k), []).append(r)
    out = []
    for kid, rs in keys.items():
        state, region, store = kid.split('|')
        slot, day, tot = {}, {}, 0
        n_stores = len({r['store'] for r in rs})
        for r in rs:
            k = r['dow'] + '|' + str(r['hour'])
            slot[k] = slot.get(k, 0) + r['orders']; day[r['dow']] = day.get(r['dow'], 0) + r['orders']; tot += r['orders']
        sl = sorted(slot.items(), key=lambda kv: -kv[1]); dy = sorted(day.items(), key=lambda kv: -kv[1])
        opn = {}
        for r in rs:
            if r['orders'] / TRAFFIC_WEEKS >= 1:
                k = r['dow'] + '|' + str(r['hour']); opn[k] = opn.get(k, 0) + 1
        qs = sorted([(k, v, v / opn[k]) for k, v in sl if (opn.get(k) or 0) >= max(1, n_stores / 2)], key=lambda x: x[2])
        quiet = qs[0] if qs else None

        def fmt(s):
            return s[0].split('|')[0][:3] + ' ' + hour_label(int(float(s[0].split('|')[1]))) if s else None
        out.append({'state': state, 'region': region, 'store': store, 'busiest_slot': fmt(sl[0] if sl else None),
                    'busiest_slot_orders': jround(sl[0][1] / TRAFFIC_WEEKS) if sl else None, 'busiest_day': dy[0][0] if dy else None,
                    'quietest_slot': fmt(quiet), 'quietest_slot_orders': jround(quiet[1] / TRAFFIC_WEEKS) if quiet else None,
                    'weekly_orders': jround(tot / TRAFFIC_WEEKS)})
    return out


def top_products_all(top_products, monthly):
    import re
    lk = 'm' + last_full_key(monthly)
    rows = sum_states(top_products, lambda r: r['item'], lambda r: {'item': r['item'], 'category': r.get('category')}, r'^([mu]\d{4}_\d{2}|stores_selling)$')
    mk = sorted(k for k in (rows[0] if rows else {}) if re.match(r'^m\d{4}_\d{2}$', k))
    i = mk.index(lk) if lk in mk else -1
    pk = mk[i - 1] if i >= 1 else None
    tot = jsum(g(r, lk) for r in rows)
    rows = sorted(rows, key=lambda r: -g(r, lk))
    for n, r in enumerate(rows):
        r['rank'] = n + 1
        r['share_pct'] = jround(g(r, lk) / tot * 1000) / 10 if tot else None
        r['mom_pct'] = jround((g(r, lk) / r[pk] - 1) * 1000) / 10 if pk and truthy(r.get(pk)) else None
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r.get('category'), []).append(r)
    for rs in by_cat.values():
        for n, r in enumerate(rs):
            r['rank_in_category'] = n + 1; r['items_in_category'] = len(rs)
    return rows


def notes_sales(stores, store_sales, w_scope, w_table, d_stats, t_stats, basket_pairs, top_products, tp_all):
    out = []
    for s, gg in nscopes(stores):
        ss = [r for r in store_sales if nin(r, s, gg)]
        down = sorted([r for r in ss if r.get('trend_pct') is not None and r['trend_pct'] <= -10], key=lambda r: r['trend_pct'])
        if down:
            out.append(nrow('sales', 'Store sales', s, gg, jnum(len(down)) + (' store is' if len(down) == 1 else ' stores are') + ' down 10%+ over the last 3 months vs the 3 before: ' +
                            nlist([r['store'] + ' (' + sign(r['trend_pct']) + ')' for r in down[:3]]) + '. Check staffing, hours and stock there first.', 2, True))
        else:
            out.append(nrow('sales', 'Store sales', s, gg, 'No store is down 10% or more over the last 3 months vs the 3 before.', 9))
        ws = sorted([r for r in w_scope if r['state'] == s and r['region'] == gg], key=lambda r: r['week'])
        lw = ws[-1] if ws else None
        if lw:
            drops = sorted([r for r in w_table if nin(r, s, gg) and r['yoy_pct'] is not None and (r['ly_week'] or 0) >= 2000 and r['yoy_pct'] <= -15], key=lambda r: r['yoy_pct'])
            out.append(nrow('weekly', 'Weekly sales', s, gg, 'Week of ' + nmon(lw['week']) + '–' + nmon(lw['week_end']) + ': ' + money(lw['net_sales']) + ', ' + sign(lw['yoy_pct']) +
                            ' vs the same week last year at the same stores.' + (' Down 15%+: ' + nlist([r['store'] + ' (' + sign(r['yoy_pct']) + ')' for r in drops[:3]]) + '.' if drops else ''),
                            1 if drops else 8, len(drops)))
        tp = [r for r in (tp_all if s == 'ALL' else [r for r in top_products if r['state'] == s and r['region'] == gg]) if r['rank'] <= 25 and r.get('mom_pct') is not None]
        if tp:
            up = sorted(tp, key=lambda r: -r['mom_pct'])[0]; dn = sorted(tp, key=lambda r: r['mom_pct'])[0]
            out.append(nrow('products', 'Top products', s, gg, 'Among the top 25 items, ' + up['item'] + ' rose most (' + sign(up['mom_pct']) + ' vs the month before) and ' + dn['item'] +
                            ' fell most (' + sign(dn['mom_pct']) + '). Check stock and placement on both.', 4 if dn['mom_pct'] <= -25 else 7, dn['mom_pct'] <= -25))
        ds = next((r for r in d_stats if r['state'] == s and r['region'] == gg), None)
        if ds and ds['pct_of_sales'] is not None:
            out.append(nrow('discounts', 'Discounts', s, gg, 'Discounts were ' + money(ds['amount']) + ' last full month, ' + jnum(ds['pct_of_sales']) +
                            '% of net sales. Watch the biggest codes in the table for any that grew faster than sales.', 3 if ds['pct_of_sales'] >= 9 else 7, ds['pct_of_sales'] >= 9))
        ts = next((r for r in t_stats if r['state'] == s and r['region'] == gg and r['store'] == ''), None)
        if ts and ts['busiest_slot']:
            out.append(nrow('hours', 'Busiest times', s, gg, 'Busiest hour: ' + ts['busiest_slot'] + ' (' + loc(ts['busiest_slot_orders']) + ' orders a week). Quietest open hour: ' +
                            (ts['quietest_slot'] or '—') + ' — schedule restocking and training then, and full coverage at the peak.', 8))
        bps = sorted([r for r in basket_pairs if (s == 'ALL' or r['state'] == s) and r['item_orders'] >= 50], key=lambda r: -r['attach_pct'])
        bp = bps[0] if bps else None
        if bp and gg == 'All':
            out.append(nrow('baskets', 'Bought together', s, gg, bp['with_item'] + ' is in ' + jnum(bp['attach_pct']) + '% of ' + bp['item'] + ' orders' +
                            (' (' + bp['state'] + ')' if s == 'ALL' else '') + '. Shelve them together or bundle them.', 7))
    return out


def promo_payback(wb_stats):
    return [{'campaign': w['campaign'], 'state': w['state'], 'region': w['region'], 'first_day': w['first_day'], 'redemptions': w['redemptions'], 'customers': w['customers'],
             'came_back': w['came_back'], 'discount_total': w['discount_total'], 'sales_after': w['sales_after'],
             'sales_per_dollar': jround(w['sales_after'] / w['discount_total'] * 100) / 100 if w['discount_total'] else None,
             'cost_per_return': jround(w['discount_total'] / w['came_back'] * 100) / 100 if w['came_back'] else None} for w in wb_stats]


def notes_customers(stores, at_risk_stores, wb_stats, payback, second_visit, now):
    out = []
    cut60 = (now - datetime.timedelta(days=60)).strftime('%Y-%m-%d')
    for s, gg in nscopes(stores):
        ar = [r for r in at_risk_stores if nin(r, s, gg)]; tot = jsum(r['at_risk'] for r in ar)
        top = sorted(ar, key=lambda r: -r['at_risk'])[0] if ar else None
        if ar:
            out.append(nrow('atrisk', 'At-risk regulars', s, gg, loc(tot) + ' regulars haven\'t been in for 30+ days' + ('; ' + top['store'] + ' has the most (' + jnum(top['at_risk']) + ')' if top and top['at_risk'] else '') +
                            '. Reach out from the At-risk tab before they settle somewhere else.', 2 if tot else 9, tot > 0))
        wbs = _sort_desc_str([r for r in wb_stats if r['state'] == s and r['region'] == gg and r['customers'] >= 20], 'first_day')
        if wbs:
            wb = wbs[0]
            out.append(nrow('winback', 'Win-back', s, gg, 'Latest code, ' + wb['campaign'] + ': ' + loc(wb['redemptions']) + ' redemptions, ' + jnum(wb['came_back_pct']) + '% of redeemers came back on a later day so far.', 6))
        pb = sorted([r for r in payback if r['state'] == s and r['region'] == gg and r['discount_total'] >= 200 and r['sales_per_dollar'] is not None and r['first_day'] and r['first_day'] <= cut60],
                    key=lambda r: -r['sales_per_dollar'])
        if len(pb) >= 2:
            out.append(nrow('payback', 'Promo payback', s, gg, 'Among codes at least 60 days old, best payback: ' + pb[0]['campaign'] + ' ($' + '%.2f' % pb[0]['sales_per_dollar'] +
                            ' of later sales per $1 of discount). Weakest: ' + pb[-1]['campaign'] + ' ($' + '%.2f' % pb[-1]['sales_per_dollar'] + '). Repeat what worked.', 5, True))
        svs = sorted([r for r in second_visit if r['store'] == '' and r['state'] == s and r['region'] == gg and r.get('back_30_pct') is not None], key=lambda r: r['month'])
        if svs:
            sv = svs[-1]
            ws = sorted([r for r in second_visit if r['store'] and r['month'] == sv['month'] and nin(r, s, gg) and (r.get('eligible_30') or 0) >= 50 and r.get('back_30_pct') is not None], key=lambda r: r['back_30_pct'])
            worst = ws[0] if ws else None
            out.append(nrow('custmix', 'New vs returning', s, gg, jnum(sv['back_30_pct']) + '% of ' + nmonth(sv['month']) + ' first-timers came back within 30 days' +
                            ('; lowest: ' + worst['store'] + ' (' + jnum(worst['back_30_pct']) + '%)' if worst else '') + '. A "come back" offer at the first visit is the lever.',
                            4 if worst and worst['back_30_pct'] < 12 else 7, bool(worst and worst['back_30_pct'] < 12)))
    return out


def notes_team(stores, team, dw, rd_rows, rd_all, rv_rows, rv_all, cr_rows):
    out = []
    for s, gg in nscopes(stores):
        ts = sorted([r for r in team if nin(r, s, gg) and (r.get('standout_count') or 0) >= 2], key=lambda r: (-r['standout_count'], -r['net_sales']))
        if ts:
            out.append(nrow('team', 'Team scorecard', s, gg, 'Recognize ' + nlist([r['employee'] + ' (' + r['store'] + ')' for r in ts[:3]]) + ' — each leads their store on two or more measures.', 6, True))
        fl = sorted([r for r in dw if nin(r, s, gg) and (r.get('flag_count') or 0) > 0], key=lambda r: (-r['flag_count'], -r['score']))
        if fl:
            out.append(nrow('abuse', 'Team discount watch', s, gg, jnum(len(fl)) + ' team member' + (' is' if len(fl) == 1 else 's are') + ' worth a look; start with ' + fl[0]['employee'] + ' at ' +
                            fl[0]['store'] + ' (' + fl[0]['flags'].split(' · ')[0] + ').', 2, True))
        else:
            out.append(nrow('abuse', 'Team discount watch', s, gg, 'No team member is flagged for unusual discounts in the last 30 days.', 9))
        rds = sorted([r for r in (rd_all if s == 'ALL' else [r for r in rd_rows if r['state'] == s and r['region'] == gg]) if r['units_sold'] >= 100], key=lambda r: -r['problem_rate_pct'])
        rvs = sorted([r for r in (rv_all if s == 'ALL' else [r for r in rv_rows if r['state'] == s and r['region'] == gg]) if r['units_sold'] >= 50], key=lambda r: -r['problem_rate_pct'])
        rd = rds[0] if rds else None; rv = rvs[0] if rvs else None
        if rv or rd:
            top = max(rv['problem_rate_pct'] if rv else 0, rd['problem_rate_pct'] if rd else 0)
            out.append(nrow('returns', 'Returns & defects', s, gg,
                            ('Worst flavor: ' + rv['item'] + ' – ' + rv['variation'] + ', ' + jnum(rv['problem_rate_pct']) + '% of ' + loc(rv['units_sold']) + ' sold came back' if rv else '') +
                            ('. ' if rv and rd else '') +
                            ('Worst item overall (100+ sold): ' + rd['item'] + ', ' + jnum(rd['problem_rate_pct']) + '% of ' + loc(rd['units_sold']) if rd else '') +
                            ' (returned or swapped as defective, 90 days). Raise them with the vendor.', 3 if top >= 5 else 7, top >= 5))
        cr = [r for r in cr_rows if nin(r, s, gg)]
        if cr:
            most = sorted(cr, key=lambda r: -r['uses'])[0]['uses']
            out.append(nrow('reuse', 'Code reuse', s, gg, jnum(len(cr)) + ' customer' + ('' if len(cr) == 1 else 's') + ' used a one-time code more than once; the most: ' + jnum(most) +
                            ' times. Remind stores the codes are one per customer.', 4 if len(cr) >= 10 else 8, len(cr) >= 10))
    return out


def sales_trend(monthly):
    out = {}
    for m in monthly:
        for st, region in ((m['state'], 'All'), (m['state'], m['region']), ('ALL', 'All')):
            k = str(st) + '|' + str(region) + '|' + m['month']
            o = out.get(k) or {'state': st, 'region': region, 'month': m['month'], 'partial': m.get('partial'), 'net_sales': 0, 'orders': 0}
            o['net_sales'] += m['net_sales']; o['orders'] += m['orders']; out[k] = o
    return [dict(o, net_sales=jround(o['net_sales'])) for o in out.values()]


def smoke_stats(groups, monthly):
    lf = full_months(monthly)[-1]
    ms = sorted(uniq(m['month'] for m in monthly)); i = ms.index(lf) - 1
    pv = ms[i] if i >= 0 else None
    st = {}
    for m in monthly:
        if m['month'] != lf:
            continue
        if m['store'] not in st:
            st[m['store']] = {'store': m['store'], 'state': m['state'], 'region': m['region'], 'smoke': 0, 'prev': 0, 'orders': 0, 'units': 0, 'total': 0, 'total_orders': 0, 'tob': 0, 'alt': 0}
        o = st[m['store']]; o['total'] += m['net_sales']; o['total_orders'] += m['orders']
    for r in groups:
        o = st.get(r['store'])
        if not o:
            continue
        if r['group'] == 'All smoke':
            if r['month'] == lf:
                o['smoke'] += r['net_sales']; o['orders'] += r['orders']; o['units'] += r['units']
            if r['month'] == pv:
                o['prev'] += r['net_sales']
        elif r['month'] == lf:
            if r['family'] == 'Tobacco':
                o['tob'] += r['net_sales']
            else:
                o['alt'] += r['net_sales']

    def fn(rs):
        def s(f):
            return jsum(x[f] for x in rs)
        smoke, prev, tot, so, to = s('smoke'), s('prev'), s('total'), s('orders'), s('total_orders')
        return {'month': lf, 'smoke_sales': jround(smoke), 'share_pct': jround(smoke / tot * 1000) / 10 if tot else None,
                'mom_pct': jround((smoke / prev - 1) * 1000) / 10 if prev else None, 'smoke_orders': so,
                'order_share_pct': jround(so / to * 1000) / 10 if to else None, 'avg_smoke_ticket': jround(smoke / so * 100) / 100 if so else None,
                'units': s('units'), 'tobacco_sales': jround(s('tob')), 'alt_sales': jround(s('alt')), 'tobacco_pct': jround(s('tob') / smoke * 1000) / 10 if smoke else None}
    return scope_stats(list(st.values()), fn)


def returns_stats(rd_rows, rd_all):
    out = {}
    for r in rd_rows + rd_all:
        k = str(r['state']) + '|' + str(r['region'])
        if k not in out:
            out[k] = {'state': r['state'], 'region': r['region'], 'returns': 0, 'defects': 0, 'defect_amt': 0, 'top_item': None, 'top_n': -1}
        o = out[k]; o['returns'] += r['returns']; o['defects'] += r['defect_replacements']; o['defect_amt'] += r['defect_amt']
        n = r['returns'] + r['defect_replacements']
        if n > o['top_n']:
            o['top_n'] = n; o['top_item'] = r['item']
    return [{k: v for k, v in o.items() if k != 'top_n'} for o in out.values()]


# ---------------------------------------------------------------- pack
def build(data, now=None):
    """data: {dataset: rows} for every name in INPUTS. Returns the home_pack rows."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    d = data
    ars = at_risk_stats(d['at_risk_stores'], d['at_risk'])
    dws = discount_watch_stats(d['discount_watch'], d['code_reuse'])
    wbs = winback_stats(d['winback'], d['winback_stores'])
    sst = sales_stats(d['store_sales'], d['sales_monthly'])
    cm = customer_monthly(d['customer_mix'])
    rv_all = sum_problems(d['returns_variants'], lambda r: r['item'] + '|' + r['variation'], lambda r: {'item': r['item'], 'variation': r['variation'], 'category': r.get('category')})
    rd_all = sum_problems(d['returns_defects'], lambda r: r['item'], lambda r: {'item': r['item'], 'category': r.get('category')})
    d_all = discounts_all(d['discounts'], d['sales_monthly'])
    calcs = {
        'home_alerts': home_alerts(d['returns_variants'], ars, dws, wbs, sst, cm, rv_all),
        'notes_sales': notes_sales(d['stores'], d['store_sales'], weekly_scope(d['weekly_sales']), weekly_store_table(d['weekly_sales']),
                                   discount_stats(d['discounts'], d['sales_monthly'], d_all), traffic_stats(d['traffic_hours']), d['basket_pairs'],
                                   d['top_products'], top_products_all(d['top_products'], d['sales_monthly'])),
        'notes_customers': notes_customers(d['stores'], d['at_risk_stores'], wbs, promo_payback(wbs), d['second_visit'], now),
        'notes_team': notes_team(d['stores'], d['team_scorecard'], d['discount_watch'], d['returns_defects'], rd_all, d['returns_variants'], rv_all, d['code_reuse']),
        'sales_stats': sst,
        'sales_trend': sales_trend(d['sales_monthly']),
        'smoke_stats': smoke_stats(d['smoke_store_groups'], d['sales_monthly']),
        'at_risk_stats': ars,
        'discount_watch_stats': dws,
        'home_returns': [{'state': r['state'], 'region': r['region'], 'problems': r['returns'] + r['defects']} for r in returns_stats(d['returns_defects'], rd_all)],
    }
    rows = []
    for c in PACK_CALCS:
        for r in calcs[c]:
            rows.append({'calc': c, 'state': '' if r.get('state') is None else r['state'], 'region': '' if r.get('region') is None else r['region'], 'row': to_json(r)})
    return rows or [{'_empty': True}]
