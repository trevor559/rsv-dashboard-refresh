#!/usr/bin/env python3
"""Red Star dashboard — twice-daily refresh (Trevor's repo, Nov 5, 2026).

Run by the scheduled task "Red Star dashboard sheets daily refresh". The task makes the tool calls
(Google Sheets get_values, Square reporting loads, ArtifactData reads); this program finds their answers
in the session log, turns them into the dashboard's data files and prints exactly what to upload and write.

  python3 refresh.py plan   <work>                  -> prints the dashboard files to download into <work>/blobs
  python3 refresh.py build  <work> [--afternoon]   -> <work>/out/*.json + <work>/manifest.json, prints files to upload
  python3 refresh.py finish <work> <dataset>=/_blob/<id> ...   -> prints the ArtifactData batch writes + old blob ids to delete

Builds: the Google Sheets copies (Discord + text sheets every run; Competitor Tracking on its days, morning run),
daily_sales (morning run, from two Square loads), discord_home (the home screen's Discord line), data_updated.
home_pack (the home summary; only when one of its Square files changed — run plan first to download them).
The stores file must be downloaded into <work>/blobs/<blob id>.json first (Artifact read, path = the stores blob id).
"""
import datetime, glob, hashlib, json, math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODE, WORK = sys.argv[1], sys.argv[2]
AFTERNOON = '--afternoon' in sys.argv
OUT = os.path.join(WORK, 'out'); os.makedirs(OUT, exist_ok=True)
NOW = datetime.datetime.now(datetime.timezone.utc)
NOW_ISO = NOW.strftime('%Y-%m-%dT%H:%M:%SZ')
TODAY = (NOW - datetime.timedelta(hours=7)).date()          # Arizona, no daylight saving
BY = 'Claude (daily refresh)'

# The sheet IDs live only in the scheduled task's instructions; answers are matched by range (each range is unique).
DISCORD, TEXTS, COMP = 'Discord Tracking', 'Lapsed Customers Text Data', 'Competitor Tracking'
SOURCES = {  # dataset: (sheet, range exactly as the task reads it)
    'discord_updates':   (DISCORD, 'Updates!A1:H2000'),
    'discord_reactions': (DISCORD, "'Reaction summary'!A1:E500"),
    'discord_members':   (DISCORD, 'Members!A1:G5000'),
    'discord_changes':   (DISCORD, "'Member changes'!A1:E5000"),
    'discord_activity':  (DISCORD, 'Activity!A1:E20000'),
    'discord_run':       (DISCORD, 'Settings!A1:B7'),
    'discord_districts': (DISCORD, 'Districts!A1:H2000'),
    'campaign_setup':    (TEXTS, 'Campaigns!A1:M200'),
    'reply_flags':       (TEXTS, "'Reply flags'!A1:K5000"),
    'competitors':       (COMP, 'Competitors!A1:R3000'),
    'comp_stores':       (COMP, "'Store summary'!A1:N200"),
    'listings':          (COMP, "'Our listings'!A1:S200"),
    'review_history':    (COMP, "'Review history'!A1:G5000"),
    'prospects':         (COMP, 'Dispensaries!A1:Q2000'),
    'venues':            (COMP, 'Venues!A1:O3000'),
}
COMP_DAY = TODAY.day in (2, 6) and TODAY.month in (1, 2, 4, 5, 7, 8, 10, 11)
EXPECTED = [d for d, (sid, _) in SOURCES.items() if sid in (DISCORD, TEXTS) or (sid == COMP and COMP_DAY and not AFTERNOON)]
ALIAS = {'CS South': 'Jvapes CS South', 'CS North': 'JVapes CS North', 'North Academy': 'VS North Academy',
         'Powers': 'Powers (former Vapor Source)', '8th St': '8th Street', '7th St': '7th Street', 'Fillmore': 'Filmore',
         'Bell Rd': 'Bell', 'Prescott': 'Prescott Valley', 'Blanco TX': 'Blanco', 'Converse TX': 'Converse',
         'Golf Links': 'Golf Links (VZ)', 'Grant': 'Grant (VZ)', 'Tanque Verde': 'Tanque Verde (VZ)', 'Valencia': 'Valencia (VZ)'}


# ---------------------------------------------------------------- helpers
def jload(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def clean_num(x):
    """Numbers as the page writes them: whole numbers without .0."""
    if isinstance(x, float) and math.isfinite(x) and x.is_integer() and abs(x) < 2 ** 53:
        return int(x)
    return x


def js_num(t):
    """JavaScript +t for a trimmed string: '' -> 0, not a number -> None (NaN)."""
    t = t.strip()
    if t == '':
        return 0
    if not re.fullmatch(r'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?', t):
        return None
    return clean_num(float(t))


def cell(r, i):
    return '' if i < 0 or i >= len(r) or r[i] is None else str(r[i]).strip()


def day_iso(v):
    t = '' if v is None else str(v).strip()
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', t)
    if m:
        return m.group(0)
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})', t)
    return m.group(3) + '-' + m.group(1).zfill(2) + '-' + m.group(2).zfill(2) if m else None


def write_rows(path, rows):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(json.dumps({'rows': rows}, ensure_ascii=False, separators=(',', ':')))


def sha(p):
    with open(p, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def blob_id(url):
    return (url or '').rsplit('/', 1)[-1]


# ---------------------------------------------------------------- session log
def log_calls():
    """[(tool name, input, answer text)] for every answered tool call in this session's log, oldest first."""
    calls, answers, order = {}, {}, []
    for p in sorted(glob.glob(os.path.expanduser('~/.claude/projects/*/*.jsonl')), key=os.path.getmtime):
        for line in open(p, encoding='utf-8', errors='replace'):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            m = o.get('message') or {}
            content = m.get('content') if isinstance(m.get('content'), list) else []
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get('type') == 'tool_use':
                    calls[b['id']] = (b.get('name', ''), b.get('input') or {}); order.append(b['id'])
                elif b.get('type') == 'tool_result':
                    c = b.get('content')
                    answers[b.get('tool_use_id')] = c if isinstance(c, str) else ''.join(
                        x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else ''
    return [(calls[k][0], calls[k][1], answers[k]) for k in order if k in answers]


def parse_answer(t):
    m = re.search(r'saved to (\S+?\.txt)', t)
    if m and os.path.exists(m.group(1)):
        return jload(m.group(1))
    return json.loads(t.strip())


def artifact_docs(calls):
    """{(collection, doc_id): (fields, version)} from ArtifactData answers (latest wins)."""
    out = {}
    for name, inp, ans in calls:
        if not name.endswith('ArtifactData'):
            continue
        col = inp.get('collection')
        for ln in ans.splitlines():
            ln = ln.strip()
            if not ln.startswith('{"id":'):
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if isinstance(d.get('data'), dict):
                out[(col, d['id'])] = (d['data'], d.get('version'))
    return out


# ---------------------------------------------------------------- sheet shapers (same output as the page's shLoader rules)
def values_of(a, what):
    if not isinstance(a, dict) or not isinstance(a.get('values'), list):
        raise ValueError('The ' + what + ' tab came back without any values.')
    return a['values']


def dc_rows(a, what, cols):
    v = values_of(a, what)
    head = [('' if h is None else str(h)).strip().lower() for h in (v[0] if v else [])]
    idx = [head.index(c[1]) if c[1] in head else -1 for c in cols]
    rows = []
    for r in v[1:]:
        if not any(('' if x is None else str(x)).strip() for x in r):
            continue
        o = {}
        for (key, _, *typ), i in zip(cols, idx):
            t = cell(r, i); typ = typ[0] if typ else 'str'
            if typ == 'day':
                o[key] = day_iso(t)
            elif typ == 'num':
                o[key] = None if t == '' else js_num(t.replace(',', ''))
            elif typ == 'bool':
                o[key] = bool(re.fullmatch(r'(?i)yes|true', t))
            else:
                o[key] = t
        rows.append(o)
    return rows


def ct_rows(a, what, nums):
    v = values_of(a, what)
    head = [('' if h is None else str(h)).strip() for h in (v[0] if v else [])]
    rows = []
    for r in v[1:]:
        if not any(('' if x is None else str(x)).strip() for x in r):
            continue
        o = {}
        for i, k in enumerate(head):
            if not k:
                continue
            t = cell(r, i)
            if k in nums:
                o[k] = None if t == '' else js_num(re.sub(r'[,$%]', '', t))
            else:
                o[k] = None if t == '' else t
        rows.append(o)
    if not rows:
        raise ValueError('The ' + what + ' tab is empty: the Competitor Tracking script has not run yet.')
    return rows


def campaign_setup(a):
    v = values_of(a, 'Campaigns')

    def iso(x):
        t = '' if x is None else str(x).strip()
        m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})', t)
        if m:
            return m.group(1) + '-' + m.group(2).zfill(2) + '-' + m.group(3).zfill(2)
        m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})', t)
        if m:
            return ('20' + m.group(3) if len(m.group(3)) == 2 else m.group(3)) + '-' + m.group(1).zfill(2) + '-' + m.group(2).zfill(2)
        return None
    head = [('' if h is None else str(h)).lower() for h in (v[0] if v else [])]

    def col(pat):
        return next((i for i, h in enumerate(head) if re.search(pat, h)), -1)
    ci = {'name': col(r'slicktext'), 'sent_on': col(r'^sent on'), 'sent': col(r'texts sent'), 'delivered': col(r'delivered'),
          'clicks': col(r'click'), 'optouts': col(r'opt-?out'), 'cost': col(r'cost')}

    def num(r, i):
        if i < 0:
            return None
        t = re.sub(r'[$,\s]', '', '' if i >= len(r) or r[i] is None else str(r[i]))
        return None if t == '' else js_num(t)

    def raw(r, i):
        return None if i >= len(r) else r[i]
    rows = []
    for r in v[1:]:
        if not (r and r[0] and str(r[0]).strip()):
            continue
        rows.append({'campaign': str(r[0]).strip(), 'active_from': iso(raw(r, 1)), 'active_to': iso(raw(r, 2)), 'cutoff': iso(raw(r, 3)),
                     'audience': '' if raw(r, 4) is None else str(raw(r, 4)),
                     'slicktext_name': str(r[ci['name']]).strip() if ci['name'] >= 0 and raw(r, ci['name']) else '',
                     'sent_on': iso(raw(r, ci['sent_on'])) if ci['sent_on'] >= 0 else None,
                     'texts_sent': num(r, ci['sent']), 'delivered': num(r, ci['delivered']), 'clicks': num(r, ci['clicks']),
                     'opt_outs': num(r, ci['optouts']), 'text_cost': num(r, ci['cost'])})
    return rows, ['campaign', 'active_from', 'active_to', 'cutoff', 'audience', 'slicktext_name', 'sent_on', 'texts_sent', 'delivered', 'clicks', 'opt_outs', 'text_cost']


def reply_flags(a):
    v = values_of(a, 'Reply flags')

    def day(x):
        t = '' if x is None else str(x).strip()
        m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', t)
        if m:
            return m.group(0)
        m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})', t)
        return m.group(3) + '-' + m.group(1).zfill(2) + '-' + m.group(2).zfill(2) if m else t[:10]
    rows = []
    for i, r in enumerate(x for x in v[1:] if cell(x, 3)):
        rows.append({'key': cell(r, 9) or str(i + 2), 'received': day(r[0] if r else None), 'campaign': cell(r, 1),
                     'last4': re.sub(r'\D', '', cell(r, 2))[-4:], 'message': cell(r, 3), 'flag': cell(r, 4) or 'None',
                     'type': cell(r, 5), 'why': cell(r, 6), 'action': cell(r, 7), 'handled': cell(r, 10)})
    return rows, ['key', 'received', 'campaign', 'last4', 'message', 'flag', 'type', 'why', 'action', 'handled']


def discord_run(a):
    v = values_of(a, 'Settings')

    def get(label):
        r = next((x for x in v if x and str(x[0] or '').strip().lower() == label), None)
        return '' if not r or len(r) < 2 or r[1] is None else str(r[1]).strip()
    return [{'last_run': get('last run'), 'result': get('last run result'), 'channels': get('company update channel ids')}], ['last_run', 'result', 'channels']


DC = {
    'discord_updates': ('Updates', [['message_id', 'message id'], ['channel', 'channel'], ['posted', 'posted', 'day'], ['posted_by', 'posted by'], ['preview', 'preview'], ['reactions_total', 'reactions (total)', 'num'], ['link', 'link'], ['counts_read', 'reaction counts read (used by the script)']]),
    'discord_reactions': ('Reaction summary', [['message_id', 'message id'], ['channel', 'channel'], ['posted', 'posted', 'day'], ['who', 'who reacted (user id:emojis; ...)']]),
    'discord_members': ('Members', [['user_id', 'user id'], ['name', 'display name'], ['roles', 'all roles'], ['joined', 'joined server', 'day'], ['bot', 'bot', 'bool']]),
    'discord_changes': ('Member changes', [['seen_on', 'seen on', 'day'], ['change', 'change'], ['user_id', 'user id'], ['name', 'display name']]),
    'discord_activity': ('Activity', [['date', 'date', 'day'], ['channel_id', 'channel id'], ['channel', 'channel'], ['messages', 'messages', 'num'], ['people', 'people posting', 'num']]),
    'discord_districts': ('Districts', [['user_id', 'discord user id'], ['name', 'name'], ['full', 'full name (contact list / square)'], ['district', 'district (pick or fix)'], ['store', 'store (pick or fix)'], ['how', 'how it was suggested']]),
}


def shape(d, a):
    """Returns (rows, columns) for one sheet dataset."""
    if d in DC:
        what, cols = DC[d]
        return dc_rows(a, what, cols), [c[0] for c in cols]
    if d == 'discord_run':
        return discord_run(a)
    if d == 'campaign_setup':
        return campaign_setup(a)
    if d == 'reply_flags':
        return reply_flags(a)
    if d == 'competitors':
        rows = ct_rows(a, 'Competitors', ['rating', 'reviews', 'dist', 'lat', 'lng'])
        return [r for r in rows if r.get('decision') != 'Not a competitor' and r.get('lat') is not None], None
    if d == 'comp_stores':
        return ct_rows(a, 'Store summary', ['rating', 'reviews', 'rivals_1mi', 'rivals_2mi', 'rivals_24h', 'review_share', 'top_rival_reviews', 'top_rival_rating']), None
    if d == 'listings':
        return ct_rows(a, 'Our listings', ['rating', 'reviews', 'issue_count']), None
    if d == 'review_history':
        return ct_rows(a, 'Review history', ['reviews', 'rating']), None
    if d == 'prospects':
        rows = [r for r in ct_rows(a, 'Dispensaries', ['rating', 'reviews', 'lat', 'lng']) if r.get('google_status') != 'Closed']
        for r in rows:
            r['priority'] = r.get('priority') or 'B'
            r['rating'] = 0 if r.get('rating') is None else r['rating']
            r['reviews'] = 0 if r.get('reviews') is None else r['reviews']
        return rows, None
    if d == 'venues':
        rows = [r for r in ct_rows(a, 'Venues', ['rating', 'reviews', 'dist'])
                if r.get('priority') and r.get('google_status') != 'Closed' and not re.match(r'^Below', r.get('google_status') or '')]
        for r in rows:
            r['rating'] = 0 if r.get('rating') is None else r['rating']
            r['reviews'] = 0 if r.get('reviews') is None else r['reviews']
            r['dist'] = 0 if r.get('dist') is None else r['dist']
            r['maps_url'] = r.get('maps_url') or ('https://www.google.com/maps/place/?q=place_id:' + r['place_id'] if r.get('place_id') else None)
        return rows, None
    raise ValueError('no shaper for ' + d)


# ---------------------------------------------------------------- watchdog: other refreshes that missed their run
def watchdog(ds, skip):
    probs = {}

    def when(iso):
        try:
            return datetime.datetime.fromisoformat(str(iso).replace('Z', '+00:00'))
        except ValueError:
            return None
    monday = TODAY - datetime.timedelta(days=TODAY.weekday())

    def first_monday(y, m):
        d = datetime.date(y, m, 1)
        return d + datetime.timedelta(days=(7 - d.weekday()) % 7)
    fm = first_monday(TODAY.year, TODAY.month)
    if fm > TODAY:
        pm = TODAY.replace(day=1) - datetime.timedelta(days=1); fm = first_monday(pm.year, pm.month)
    for d, dd in sorted(ds.items()):
        if d in skip or d in ('data_updated', 'discord_home', 'home_pack') or (dd.get('source') or {}).get('kind') != 'file':
            continue
        at = when((dd.get('updated') or {}).get('at'))
        if not at:
            continue
        day = (at - datetime.timedelta(hours=7)).date(); sched = str(dd.get('schedule') or ''); h = dd.get('staleAfterHours')
        age = (NOW - at).total_seconds() / 3600
        if sched.startswith('Weekly, Monday') and day < monday and (TODAY > monday or AFTERNOON):
            probs['OVERDUE ' + d] = 'missed its Monday refresh (last updated %s)' % day
        elif 'first Monday' in sched and day < fm and (TODAY > fm or AFTERNOON):
            probs['OVERDUE ' + d] = 'missed its first-Monday-of-the-month refresh (last updated %s)' % day
        elif h and age > h and d not in SOURCES:
            probs['OVERDUE ' + d] = 'not updated for %d hours, limit %d (last updated %s)' % (age, h, day)
    return probs


def pack_status(ds):
    """(inputs {dataset: url}, rebuild?) for home_pack: rebuild when any input file changed since the last pack."""
    import home_pack
    want = {i: ((ds.get(i) or {}).get('source') or {}).get('url') for i in home_pack.INPUTS}
    have = (ds.get('home_pack') or {}).get('inputs') or {}
    return want, '--force-pack' in sys.argv or any(want[i] != have.get(i) for i in want) or not (ds.get('home_pack') or {}).get('source')


# ---------------------------------------------------------------- plan: which dashboard files to download
if MODE == 'plan':
    docs = artifact_docs(log_calls())
    ds = {i: f for (c, i), (f, v) in docs.items() if c == 'datasets'}
    if not ds:
        raise SystemExit('no datasets docs in this session: read them with ArtifactData (list, collection "datasets", limit 200) first')
    want, rebuild = pack_status(ds)
    need = ['stores'] + ([i for i in want if i != 'stores'] if rebuild else [])
    print('home summary needs rebuilding:', rebuild)
    print('Download each of these with the Artifact tool (action read, url = the dashboard, path = id, out_dir = ' + os.path.join(WORK, 'blobs') + '):')
    for i in need:
        print('  ' + i + '  ' + blob_id(want.get(i) or ((ds.get(i) or {}).get('source') or {}).get('url')))
    sys.exit(0)


# ---------------------------------------------------------------- build
if MODE == 'build':
    calls = log_calls()
    docs = artifact_docs(calls)
    ds = {i: f for (c, i), (f, v) in docs.items() if c == 'datasets'}
    if not ds:
        raise SystemExit('no datasets docs in this session: read them with ArtifactData (list, collection "datasets", limit 200) first')
    st = dict((docs.get(('ops', 'sheets_state')) or ({}, None))[0])
    if not st:
        raise SystemExit('no ops/sheets_state in this session: read it with ArtifactData get first')
    for k in ('hashes', 'rows', 'changed'):
        st[k] = dict(st.get(k) or {})
    stores_p = os.path.join(WORK, 'blobs', blob_id((ds['stores'].get('source') or {}).get('url')) + '.json')
    if not os.path.exists(stores_p):
        raise SystemExit('stores file missing: download blob ' + blob_id(ds['stores']['source']['url']) + ' into ' + os.path.join(WORK, 'blobs'))
    stores = jload(stores_p); stores = stores if isinstance(stores, list) else stores['rows']
    summary, built = {}, {}

    # sheet copies
    latest = {}
    for name, inp, ans in calls:
        if name.endswith('get_values'):
            latest[inp.get('range')] = ans
    for d in EXPECTED:
        key = SOURCES[d][1]
        if key not in latest:
            summary[d] = {'error': 'no get_values answer in this session for ' + SOURCES[d][0] + ' ' + key}; continue
        try:
            rows, cols = shape(d, parse_answer(latest[key]))
            if not rows:
                rows = [dict({c: None for c in (cols or [])}, _empty=True)]
            p = os.path.join(OUT, d + '.json'); write_rows(p, rows)
            built[d] = p; summary[d] = {'rows': len(rows)}
        except Exception as e:  # report and keep the old file
            summary[d] = {'error': str(e)[:300]}

    # daily_sales (morning)
    if not AFTERNOON:
        by = {}
        for name, inp, ans in calls:
            if not name.endswith('make_api_request_read') or str(inp.get('service', '')).lower() != 'reporting':
                continue
            q = (inp.get('request') or {}).get('query') or {}
            td = (q.get('timeDimensions') or [{}])[0]
            if q.get('dimensions') != ['Sales.location_name'] or td.get('granularity') != 'day' or 'Sales.net_sales' not in (q.get('measures') or []):
                continue
            try:
                for r in parse_answer(ans).get('data') or []:
                    day = str(r.get('Sales.reporting_day.day') or r.get('Sales.reporting_day') or '')[:10]
                    by[(r.get('Sales.location_name'), day)] = (round(float(r.get('Sales.net_sales') or 0), 2), int(float(r.get('Sales.order_count') or 0)))
            except Exception as e:
                summary['daily_sales'] = {'error': 'could not read a Square answer: ' + str(e)[:200]}
        if by and 'daily_sales' not in summary:
            smap = {s['store']: s for s in stores}; unmatched = set()
            yday = TODAY - datetime.timedelta(days=1); first = yday - datetime.timedelta(days=41)
            out = []
            for loc in sorted({k[0] for k in by}):
                n = re.sub(r'^\d+\s+', '', str(loc or '')).strip(); s = smap.get(ALIAS.get(n, n))
                if not s:
                    unmatched.add(loc); continue
                d = first
                while d <= yday:
                    cur = by.get((loc, d.isoformat())); ly = by.get((loc, (d - datetime.timedelta(days=364)).isoformat()))
                    if cur or ly:
                        out.append({'store': s['store'], 'state': s['state'], 'region': s['region'], 'date': d.isoformat(),
                                    'net_sales': clean_num(cur[0]) if cur else 0, 'orders': cur[1] if cur else 0,
                                    'ly_net_sales': clean_num(ly[0]) if ly else None, 'ly_orders': ly[1] if ly else None})
                    d += datetime.timedelta(days=1)
            out.sort(key=lambda r: (r['store'], r['date']))
            if not any(r['date'] == yday.isoformat() for r in out):
                summary['daily_sales'] = {'error': 'no sales for ' + yday.isoformat() + ' in the Square answers'}
            else:
                p = os.path.join(OUT, 'daily_sales.json'); write_rows(p, out); built['daily_sales'] = p
                summary['daily_sales'] = {'rows': len(out), 'yesterday': yday.isoformat(),
                                          'chain_yesterday': round(sum(r['net_sales'] for r in out if r['date'] == yday.isoformat()), 2),
                                          'unmatched_locations': sorted(unmatched)}
        elif 'daily_sales' not in summary:
            summary['daily_sales'] = {'error': 'no Square daily sales answer in this session'}

    # discord_home: the home screen's Discord line, from this run's Discord copies
    need = ['discord_updates', 'discord_reactions', 'discord_members', 'discord_districts', 'discord_run']
    if all(d in built for d in need):
        import discord_home
        rd = {d: jload(built[d])['rows'] for d in need}
        rows = discord_home.home_lines(stores, rd['discord_updates'], rd['discord_reactions'], rd['discord_members'],
                                       rd['discord_districts'], rd['discord_run'], TODAY.isoformat())
        if not rows:
            rows = [{'_empty': True}]
        p = os.path.join(OUT, 'discord_home.json'); write_rows(p, rows); built['discord_home'] = p
        summary['discord_home'] = {'rows': len(rows)}
    else:
        summary['discord_home'] = {'error': 'skipped: a Discord tab could not be copied this run'}

    # home_pack: the home summary, only when one of its Square files changed
    pack_inputs = None
    want, rebuild = pack_status(ds)
    if rebuild:
        paths = {i: os.path.join(WORK, 'blobs', blob_id(u) + '.json') for i, u in want.items()}
        missing_files = [i for i, p in paths.items() if not os.path.exists(p)]
        if missing_files:
            summary['home_pack'] = {'error': 'needs rebuilding but these files were not downloaded (run plan): ' + ', '.join(missing_files)}
        else:
            import home_pack
            data = {}
            for i, p in paths.items():
                x = jload(p); data[i] = x if isinstance(x, list) else x['rows']
            rows = home_pack.build(data, NOW)
            p = os.path.join(OUT, 'home_pack.json'); write_rows(p, rows); built['home_pack'] = p
            summary['home_pack'] = {'rows': len(rows)}; pack_inputs = want

    # a copy that lost more than half its rows is not uploaded
    for d in list(built):
        old = st['rows'].get(d)
        if d in SOURCES and old and summary[d]['rows'] < old / 2:
            summary[d] = {'error': 'row count dropped from %d to %d; kept the old file' % (old, summary[d]['rows'])}; del built[d]

    upload, touch = [], []
    for d, p in built.items():
        h = sha(p)
        if h != st['hashes'].get(d) or not (ds.get(d) or {}).get('source'):
            upload.append({'dataset': d, 'file': p, 'old_url': ((ds.get(d) or {}).get('source') or {}).get('url')})
            st['hashes'][d] = h; st['changed'][d] = NOW_ISO
        else:
            touch.append(d)
        st['rows'][d] = summary[d].get('rows')

    # data_updated: when each source's data last changed
    rows = []
    for d, dd in sorted(ds.items()):
        if d == 'data_updated' or (dd.get('source') or {}).get('kind') == 'query':
            continue
        at = st['changed'].get(d) if d in SOURCES or d in ('daily_sales', 'discord_home', 'home_pack') else None
        at = at or (dd.get('updated') or {}).get('at')
        if at:
            row = {'dataset': d, 'updated_at': at, 'stale_h': dd.get('staleAfterHours')}
            if d in built:
                row['checked_at'] = NOW_ISO
            rows.append(row)
    p = os.path.join(OUT, 'data_updated.json'); write_rows(p, rows)
    upload.append({'dataset': 'data_updated', 'file': p, 'old_url': ((ds.get('data_updated') or {}).get('source') or {}).get('url')})
    st['updated'] = TODAY.isoformat()

    errors = {d: r['error'] for d, r in summary.items() if 'error' in r}
    errors.update(watchdog(ds, set(built)))
    versions = {c + '/' + i: v for (c, i), (f, v) in docs.items()}
    json.dump({'upload': upload, 'touch': touch, 'errors': errors, 'summary': summary, 'state': st, 'versions': versions, 'pack_inputs': pack_inputs},
              open(os.path.join(WORK, 'manifest.json'), 'w'), indent=1)
    print(json.dumps(summary, indent=1))
    print('\nUpload each of these with the Artifact tool (action publish, url = the dashboard, asset: true, file_path):')
    for u in upload:
        print('  ' + u['dataset'] + '  ' + u['file'])
    if errors:
        print('\nPROBLEMS (report these):', json.dumps(errors, indent=1))
    sys.exit(0)


# ---------------------------------------------------------------- finish
if MODE == 'finish':
    man = jload(os.path.join(WORK, 'manifest.json'))
    urls = dict(a.split('=', 1) for a in sys.argv[3:])
    ddir = os.path.join(WORK, 'docs'); os.makedirs(ddir, exist_ok=True)
    ver = man['versions']; writes, delete, missing, nover = [], [], [], []

    def add(collection, doc_id, fields):
        p = os.path.join(ddir, collection.replace('/', '_') + '__' + doc_id + '.json')
        json.dump(fields, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
        v = ver.get(collection + '/' + doc_id)
        if not v:
            nover.append(collection + '/' + doc_id)
        writes.append({k: x for k, x in {'op': 'update', 'collection': collection, 'doc_id': doc_id, 'file_path': p, 'if_version': v}.items() if x is not None})
    for u in man['upload']:
        d = u['dataset']
        if d not in urls:
            missing.append(d); continue
        fields = {'source': {'kind': 'file', 'url': urls[d], 'name': d + '.json', 'format': 'json'}, 'updated': {'at': NOW_ISO, 'by': BY}}
        if d == 'home_pack' and man.get('pack_inputs'):
            fields['inputs'] = man['pack_inputs']
        add('datasets', d, fields)
        if u.get('old_url') and blob_id(u['old_url']) != blob_id(urls[d]):
            delete.append(blob_id(u['old_url']))
    for d in man['touch']:
        add('datasets', d, {'updated': {'at': NOW_ISO, 'by': BY}})
    if not missing:
        add('ops', 'sheets_state', man['state'])
    if missing:
        print('NOT UPLOADED (no url given; their docs and ops/sheets_state were left alone):', missing)
    if nover:
        print('NO VERSION FOUND for', nover, '- get those docs with ArtifactData (no out_dir) and add if_version')
    print('ArtifactData batch writes (url = the dashboard, one batch call):')
    print(json.dumps(writes))
    print('\nAfter the batch succeeds, delete these old files (Artifact action delete, url = the dashboard, path = id):')
    print(json.dumps(delete))
    sys.exit(0)

raise SystemExit('mode must be plan, build or finish')
