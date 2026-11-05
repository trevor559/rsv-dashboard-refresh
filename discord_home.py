"""Discord line for the dashboard's home screen (dataset discord_home).

Same result as the page's discord_home_lines calc: for the latest company update posted before today in the
tracked company-wide channels, per state and district (plus company-wide), how many employees (joined by then;
"Warehouse & office" and "Not an employee" left out) haven't reacted yet, and the stores with the most still to react.
Inputs are the shaped sheet copies (rows as refresh.py writes them) and the stores file.
"""
import datetime, json, re

EXCLUDED = ('Not an employee', 'Warehouse & office')


def tracked_channels(run_rows):
    raw = str((run_rows[0] if run_rows else {}).get('channels') or '')
    return {re.sub(r'\D', '', x) for x in re.split(r'[,\s]+', raw) if re.sub(r'\D', '', x)}


def channel_id(link):
    p = str(link or '').split('/')
    return p[-2] if len(p) >= 3 else ''


def unpack_reactions(reactions):
    rows = []
    for u in reactions:
        if u.get('user_id'):
            rows.append(u); continue
        for part in str(u.get('who') or '').split(';'):
            i = part.find(':')
            if i < 1:
                continue
            uid = part[:i].strip()
            for e in part[i + 1:].strip().split(' '):
                if e:
                    rows.append({'message_id': u.get('message_id'), 'channel': u.get('channel'), 'posted': u.get('posted'), 'emoji': e, 'user_id': uid})
    return rows


def member_district(members, districts):
    by_id, by_name = {}, {}
    for d in districts:
        if not d.get('district') and not d.get('full'):
            continue
        v = {'district': d.get('district') or '', 'store': d.get('store') or '', 'full': d.get('full') or ''}
        if d.get('user_id'):
            by_id[d['user_id']] = v
        elif d.get('name'):
            by_name[str(d['name']).strip().lower()] = v
    out = []
    for m in members:
        if m.get('bot'):
            continue
        v = by_id.get(m.get('user_id')) or by_name.get(str(m.get('name') or '').strip().lower())
        district = v['district'] if v and v['district'] else 'No district yet'
        if v and v['store']:
            store = v['store']
        elif district in ('No district yet', 'Not an employee'):
            store = ''
        elif district == 'Warehouse & office':
            store = 'Warehouse & office'
        else:
            store = 'District-wide'
        out.append({'user_id': m.get('user_id'), 'name': (v and v['full']) or m.get('name') or 'No name set', 'joined': m.get('joined'), 'district': district, 'store': store})
    return out


def update_stats(updates, rx, members, run_rows):
    """Only the fields the home line needs: message_id, channel, posted, complete."""
    tracked = tracked_channels(run_rows)
    by_msg = {}
    for r in rx:
        by_msg.setdefault(r['message_id'], []).append(r)
    out = []
    for u in updates:
        if tracked and channel_id(u.get('link')) not in tracked:
            continue
        read_total = 0
        try:
            for n in json.loads(u.get('counts_read') or '{}').values():
                try:
                    read_total += float(n) or 0
                except (TypeError, ValueError):
                    pass
        except ValueError:
            read_total = 0
        total = u.get('reactions_total') or 0
        out.append({'message_id': u.get('message_id'), 'channel': u.get('channel'), 'posted': u.get('posted'),
                    'complete': total == 0 or read_total >= total})
    return out


def district_people(ups, rx, md):
    ids = {u['message_id'] for u in ups}
    em = {}
    for r in rx:
        if r['message_id'] not in ids:
            continue
        k = (r['message_id'], r['user_id'])
        em[k] = (em[k] + ' ' if em.get(k) else '') + r['emoji']
    people = [m for m in md if m['district'] not in EXCLUDED]
    out = []
    for u in ups:
        for m in people:
            if m.get('joined') and u.get('posted') and m['joined'] > u['posted']:
                continue
            e = em.get((u['message_id'], m['user_id']))
            out.append({'message_id': u['message_id'], 'user_id': m['user_id'], 'name': m['name'], 'district': m['district'],
                        'store': m['store'], 'reacted': 'Yes' if e else 'Not yet'})
    return out


def scopes(stores):
    out = [('ALL', 'All')]
    states = list(dict.fromkeys(s['state'] for s in stores))
    for st in states:
        out.append((st, 'All'))
        for g in dict.fromkeys(s['region'] for s in stores if s['state'] == st):
            out.append((st, g))
    return out


def n_num(v):
    return '{:,}'.format(int(round(v)))


def n_list(a):
    return ''.join(a) if len(a) <= 1 else ', '.join(a[:-1]) + ' and ' + a[-1]


def home_lines(stores, updates, reactions, members, districts, run_rows, today):
    rx = unpack_reactions(reactions)
    md = member_district(members, districts)
    ups = update_stats(updates, rx, members, run_rows)
    cands = [x for x in ups if x.get('posted') and x['posted'] < today]
    if not cands:
        return []
    u = sorted(cands, key=lambda x: (str(x['posted']), len(str(x['message_id'])), str(x['message_id'])))[-1]
    ppl = [p for p in district_people(ups, rx, md) if p['message_id'] == u['message_id']]
    store_state = {s['store']: s['state'] for s in stores}
    dist_states = {}
    for s in stores:
        dist_states.setdefault(s['region'], [])
        if s['state'] not in dist_states[s['region']]:
            dist_states[s['region']].append(s['state'])

    def states_of(p):
        return [store_state[p['store']]] if p['store'] and p['store'] in store_state else list(dist_states.get(p['district'], []))
    d = datetime.date.fromisoformat(u['posted'])
    day = d.strftime('%b') + ' ' + str(d.day)
    ch = re.sub(r'[^\w\s&-]', '', str(u.get('channel') or ''), flags=re.ASCII)
    ch = re.sub(r'^[-\s]+|[-\s]+$', '', ch)
    out = []
    for s, g in scopes(stores):
        mine = [p for p in ppl if s == 'ALL' or (s in states_of(p) and (g == 'All' or p['district'] == g))]
        if not mine:
            out.append({'state': s, 'region': g}); continue
        no = [p for p in mine if p['reacted'] != 'Yes']
        share = len(no) / len(mine)

        def where(p):
            if not p['district'] or p['district'] == 'No district yet':
                return 'No district yet'
            if not p['store'] or p['store'] == 'District-wide':
                return p['district'] + ', district-wide' if g == 'All' else 'District-wide'
            return p['store']
        by = {}
        for p in no:
            k = where(p); by[k] = by.get(k, 0) + 1
        top = [k + ' (' + str(n) + ')' for k, n in sorted(by.items(), key=lambda kv: -kv[1])[:3]]
        out.append({'state': s, 'region': g, 'key': 'discord|' + u['message_id'], 'level': 'watch' if share > 0.3 else 'info', 'area': 'Discord', 'tab': 'dcwho',
                    'headline': 'Latest company update (' + day + (', #' + ch if ch else '') + '): ' + n_num(len(no)) + ' of ' + n_num(len(mine)) + ' haven’t reacted',
                    'detail': ('Most still to react: ' + n_list(top) + '. ' if top else 'Everyone has reacted. ') +
                              ('' if u['complete'] else 'The bot is still reading this update’s reactions, so the count may drop. ') + 'Follow up lists the names.',
                    'sort': 90})
    return out
