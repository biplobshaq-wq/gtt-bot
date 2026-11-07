"""Game Time Tonight bot (runs hourly on GitHub Actions).
1) Publishes 1 game preview per run (best upcoming game, kickoff in 3-30h), max DAILY_CAP per ET day.
2) After games end, adds the final score to the post (no AI needed).
3) 0-3h before kickoff, sends the matchup card to the Facebook webhook (Make.com) for top games.
Blogger publishing + Gemini go through the owner's Apps Script web app."""
import base64, datetime as dt, html, json, os, re, subprocess, sys, time, urllib.request
from zoneinfo import ZoneInfo
from card import make_card

WEBAPP = os.environ.get('WEBAPP', '').strip()
SECRET = os.environ.get('WEB_SECRET', '').strip()
FB_HOOK = os.environ.get('FB_WEBHOOK', '').strip()
BLOG_ID = '8757754119349417883'
REPO_RAW = 'https://raw.githubusercontent.com/biplobshaq-wq/gtt-bot/main/'
ET, PT, CT = ZoneInfo('America/New_York'), ZoneInfo('America/Los_Angeles'), ZoneInfo('America/Chicago')
DAILY_CAP = int(os.environ.get('DAILY_CAP', '12'))
FB_DAILY_CAP = 6
STATE = 'state.json'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/'
LEAGUES = [('football/nfl', 'NFL'), ('football/college-football', 'College Football'), ('basketball/nba', 'NBA')]
NATIONAL = {'ABC', 'CBS', 'FOX', 'NBC', 'ESPN', 'ESPN2', 'TNT', 'TRUTV', 'NBA TV', 'PRIME VIDEO', 'PEACOCK', 'NETFLIX', 'NFL NET', 'NFL NETWORK', 'BIG TEN NETWORK', 'BTN', 'SEC NETWORK', 'ACC NETWORK', 'FS1', 'CW NETWORK', 'THE CW'}
STREAM = {
    'FOX': 'the FOX One app, YouTube TV, Hulu + Live TV, Sling Blue or Fubo', 'FS1': 'FOX One, YouTube TV, Hulu + Live TV, Sling Blue or Fubo',
    'CBS': 'Paramount+ (Premium plan), YouTube TV, Hulu + Live TV or Fubo', 'NBC': 'Peacock, YouTube TV, Hulu + Live TV or Fubo',
    'PEACOCK': 'Peacock', 'ABC': 'the ESPN app, YouTube TV, Hulu + Live TV, Sling Orange or Fubo',
    'ESPN': 'the ESPN app (ESPN Unlimited), YouTube TV, Hulu + Live TV, Sling Orange or Fubo', 'ESPN2': 'the ESPN app, YouTube TV, Hulu + Live TV or Sling Orange',
    'NFL NET': 'NFL+, YouTube TV, Sling Blue or Fubo', 'PRIME VIDEO': 'Prime Video', 'NETFLIX': 'Netflix',
    'TNT': 'HBO Max, YouTube TV, Hulu + Live TV or Sling Orange', 'TRUTV': 'HBO Max, YouTube TV, Hulu + Live TV or Sling',
    'NBA TV': 'NBA League Pass, YouTube TV or Sling', 'BIG TEN NETWORK': 'FOX One, YouTube TV, Hulu + Live TV or Fubo', 'BTN': 'FOX One, YouTube TV, Hulu + Live TV or Fubo',
    'SEC NETWORK': 'the ESPN app, YouTube TV, Hulu + Live TV or Sling', 'ACC NETWORK': 'the ESPN app, YouTube TV, Hulu + Live TV or Sling',
}
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'}


def get_json(url):
    for i in range(3):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read())
        except Exception as e:
            err = e; time.sleep(3)
    raise err


def web(payload, timeout=380):
    payload = dict(payload, secret=SECRET, blogId=BLOG_ID)
    req = urllib.request.Request(WEBAPP, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    if not r.get('ok'):
        raise RuntimeError('web app: ' + str(r.get('error'))[:300])
    return r


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {'games': {}, 'daily': {}, 'fbdaily': {}}


def save_state(s):
    # keep last 400 games
    g = s['games']
    if len(g) > 400:
        for k in sorted(g, key=lambda k: g[k].get('date', ''))[:len(g) - 400]:
            del g[k]
    json.dump(s, open(STATE, 'w'), indent=1)


def git_push(msg, paths):
    try:
        subprocess.run(['git', 'add'] + paths, check=True)
        if subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode != 0:
            subprocess.run(['git', 'commit', '-q', '-m', msg], check=True)
            subprocess.run(['git', 'pull', '-q', '--rebase'], check=False)
            subprocess.run(['git', 'push', '-q'], check=True)
    except Exception as e:
        print('git push failed:', e)


def tv_names(comp):
    out = []
    for b in comp.get('broadcasts', []) or []:
        for n in b.get('names', []) or []:
            if n not in out:
                out.append(n)
    return out


def score_game(league, comp, tv):
    t = {c['homeAway']: c for c in comp['competitors']}
    up = {n.upper() for n in tv}
    nat = bool(up & NATIONAL)
    if league == 'football/nfl':
        return 100 + (20 if nat and ('NBC' in up or 'PRIME VIDEO' in up or 'ESPN' in up or 'ABC' in up) else 0)
    if league == 'football/college-football':
        ranks = [int((c.get('curatedRank') or {}).get('current', 99) or 99) for c in t.values()]
        r = sum(1 for x in ranks if x <= 25)
        s = (60 if r >= 1 else 0) + (30 if r == 2 else 0) + (20 if nat and up & {'ABC', 'CBS', 'FOX', 'NBC', 'ESPN'} else 0)
        return s
    if league == 'basketball/nba':
        return 50 if nat else 20
    return 0


def candidates(now):
    out = []
    for league, name in LEAGUES:
        for d in (now, now + dt.timedelta(days=1)):
            url = ESPN + league + '/scoreboard?dates=' + d.strftime('%Y%m%d') + ('&groups=80&limit=300' if 'college' in league else '')
            try:
                j = get_json(url)
            except Exception as e:
                print('scoreboard fail', league, e); continue
            for e in j.get('events', []):
                comp = e['competitions'][0]
                if comp.get('status', {}).get('type', {}).get('state') != 'pre':
                    continue
                ko = dt.datetime.fromisoformat(e['date'].replace('Z', '+00:00'))
                tv = tv_names(comp)
                out.append({'id': e['id'], 'league': league, 'lname': name, 'ko': ko, 'tv': tv,
                            'score': score_game(league, comp, tv), 'name': e.get('name', ''), 'week': (j.get('week') or {}).get('number')})
    uniq = {}
    for c in out:
        uniq[c['id']] = c
    return list(uniq.values())


# ---------------------------------------------------------------- facts + writing
def team_obj(c):
    t = c['team']
    logo = (t.get('logos') or [{}])[0].get('href') or t.get('logo', '')
    return {'name': t.get('displayName'), 'short': t.get('shortDisplayName') or t.get('location') or t.get('displayName'),
            'nick': t.get('name'), 'loc': t.get('location'), 'abbr': t.get('abbreviation'), 'logo': logo,
            'color': t.get('color', ''), 'rank': c.get('rank') or (c.get('curatedRank') or {}).get('current'),
            'record': (c.get('record') or [{}])[0].get('summary') if c.get('record') else ''}


def facts_for(g):
    j = get_json(ESPN + g['league'] + '/summary?event=' + g['id'])
    comp = j['header']['competitions'][0]
    t = {c['homeAway']: c for c in comp['competitors']}
    away, home = team_obj(t['away']), team_obj(t['home'])
    venue = (j.get('gameInfo') or {}).get('venue') or {}
    addr = venue.get('address') or {}
    leaders = []
    for blk in j.get('leaders', []) or []:
        tn = (blk.get('team') or {}).get('displayName', '')
        for cat in (blk.get('leaders') or [])[:3]:
            l0 = (cat.get('leaders') or [{}])[0]
            ath = (l0.get('athlete') or {}).get('displayName')
            if ath:
                leaders.append(f"{tn} {cat.get('displayName')}: {ath} ({l0.get('displayValue', '')})")
    last5 = []
    for blk in j.get('lastFiveGames', []) or []:
        tn = (blk.get('team') or {}).get('displayName', '')
        res = []
        for ev in (blk.get('events') or [])[:5]:
            res.append(f"{ev.get('gameResult', '')} {ev.get('atVs', '')} {(ev.get('opponent') or {}).get('displayName', '')} {ev.get('score', '')}".strip())
        if res:
            last5.append(tn + ': ' + '; '.join(res))
    inj = []
    for blk in j.get('injuries', []) or []:
        tn = (blk.get('team') or {}).get('displayName', '')
        for it in (blk.get('injuries') or [])[:4]:
            if (it.get('status') or '').lower() in ('out', 'doubtful', 'injured reserve'):
                inj.append(f"{tn}: {(it.get('athlete') or {}).get('displayName')} ({it.get('status')})")
    ko = g['ko']
    return {
        'league': g['lname'], 'week': g.get('week'), 'away': away, 'home': home,
        'neutral': comp.get('neutralSite', False),
        'venue': venue.get('fullName', ''), 'city': ', '.join(x for x in [addr.get('city'), addr.get('state') or addr.get('country')] if x),
        'kickoff_et': ko.astimezone(ET).strftime('%A, %B %-d, %Y at %-I:%M %p ET').replace(':00 ', ' '),
        'kickoff_pt': ko.astimezone(PT).strftime('%-I:%M %p PT').replace(':00 ', ' '),
        'kickoff_ct': ko.astimezone(CT).strftime('%-I:%M %p CT').replace(':00 ', ' '),
        'tv': g['tv'], 'leaders': leaders[:8], 'last5': last5, 'injuries': inj[:8],
    }


def prompt_for(f):
    word = 'tip-off' if f['league'] == 'NBA' else 'kickoff'
    return f"""You are a US sports writer for "Game Time Tonight". Write a short, accurate game preview in American English.
STRICT RULES: Use ONLY the facts below. Do not invent stats, injuries, quotes, odds, or past results. No betting advice.
Never say you stream the game. Friendly, clear, 8th-grade reading level. No markdown.
FACTS (JSON): {json.dumps(f, default=str)}
Return ONLY a JSON object with these keys:
"intro": 2-3 sentences: who plays, when ({word} time ET), where, and the TV channel.
"preview": array of 3 short paragraphs (form, key matchups, what to watch) based only on the facts.
"keys": array of 3 short "players/things to watch" bullet strings based only on the facts.
"faq": array of 4 objects {{"q","a"}}: what time is the game, what channel, where is it played, how to follow the live score (answer: on this page, the score box updates automatically).
"meta": one sentence under 155 characters for a search snippet."""


def esc(s):
    return html.escape(str(s or ''), quote=False)


def build_html(g, f, ai, img_url):
    a, h = f['away'], f['home']
    word = 'Tip-off' if f['league'] == 'NBA' else 'Kickoff'
    tv = ', '.join(f['tv']) or 'TBA (check local listings)'
    streams = []
    for n in f['tv']:
        s = STREAM.get(n.upper())
        if s and s not in streams:
            streams.append(f'{esc(n)}: {esc(s)}')
    if f['league'] == 'NBA':
        streams.append('Out-of-market games: NBA League Pass')
    stream_html = '<br/>'.join(streams) or 'Live TV streaming services that carry the channel above'
    rows = [('Date &amp; time', f"{esc(f['kickoff_et'])} ({esc(f['kickoff_ct'])} / {esc(f['kickoff_pt'])})"),
            ('TV channel', esc(tv)), ('Streaming', stream_html),
            ('Venue', esc(f['venue']) + (', ' + esc(f['city']) if f['city'] else ''))]
    if a.get('record') or h.get('record'):
        rows.append(('Records', f"{esc(a['name'])} {esc(a.get('record'))} &#183; {esc(h['name'])} {esc(h.get('record'))}"))
    table = '<table>' + ''.join(f'<tr><th>{k}</th><td>{v}</td></tr>' for k, v in rows) + '</table>'
    prev = ''.join(f'<p>{esc(p)}</p>' for p in ai.get('preview', [])[:3])
    keys = ''.join(f'<li>{esc(k)}</li>' for k in ai.get('keys', [])[:3])
    faq = ''.join(f"<p><b>{esc(x.get('q'))}</b><br/>{esc(x.get('a'))}</p>" for x in ai.get('faq', [])[:4] if isinstance(x, dict))
    return f"""<img alt="{esc(a['short'])} vs {esc(h['short'])} {word.lower()} time and TV channel" src="{img_url}" width="1200" height="675"/>
<div class="gtt-live" data-league="{g['league']}" data-event="{g['id']}"><div class="st">Loading live score…</div></div>
<p>{esc(ai.get('intro'))}</p>
<h2>How to Watch {esc(a['short'])} vs {esc(h['short'])}</h2>
{table}
<h2>Game Preview</h2>
{prev}
{('<h2>Players and Things to Watch</h2><ul>' + keys + '</ul>') if keys else ''}
<h2>Live Score</h2>
<p>Keep this page open during the game. The score box at the top updates automatically every 30 seconds, and the final score is added here after the game.</p>
<h2>FAQ</h2>
{faq}
<p><i>Game Time Tonight does not stream games. Times and channels come from public schedules and can change; check your local listings.</i></p>"""


def title_for(f):
    a, h = f['away'], f['home']
    d = f['kickoff_et'].split(',')[1].strip().split(' at ')[0]  # "November 8"
    d = re.sub(r'\s+\d{4}$', '', d)
    if f['league'] == 'NBA':
        return f"{a['nick']} vs {h['nick']}: Tip-Off Time, TV Channel & Live Score ({d})"
    if f['league'] == 'NFL':
        wk = f" (Week {f['week']})" if f.get('week') else ''
        return f"{a['nick']} vs {h['nick']}: Kickoff Time, TV Channel & Live Score{wk}"
    return f"{a['short']} vs {h['short']}: Kickoff Time, TV Channel & Live Score ({d})"


def labels_for(f):
    l = [f['league'], 'Preview', f['away']['name'], f['home']['name']]
    l += [n for n in f['tv'][:2] if n.upper() in ('ESPN', 'FOX', 'CBS', 'NBC', 'ABC', 'PRIME VIDEO', 'TNT', 'NETFLIX', 'PEACOCK')]
    return list(dict.fromkeys(l))


def publish_preview(g, state, now):
    f = facts_for(g)
    print('Writing:', f['away']['name'], 'at', f['home']['name'])
    ai = json.loads(re.sub(r'^```(json)?|```$', '', web({'action': 'gemini', 'prompt': prompt_for(f)})['text'].strip()))
    os.makedirs('img', exist_ok=True)
    ko = g['ko'].astimezone(ET)
    word = 'TIP-OFF' if f['league'] == 'NBA' else 'KICKOFF'
    line1 = ko.strftime('%a, %b ').upper() + str(ko.day) + ' · ' + word + ' ' + ko.strftime('%-I:%M %p ET').replace(':00 ', ' ')
    line2 = ('Watch on ' + ', '.join(g['tv'][:2]) if g['tv'] else 'TV: check local listings') + ' · Live score inside'
    path = f"img/{g['id']}.jpg"
    A = {'name': f['away']['short'], 'logo': f['away']['logo'], 'color': f['away']['color']}
    H = {'name': f['home']['short'], 'logo': f['home']['logo'], 'color': f['home']['color']}
    make_card(A, H, line1, line2, path, f['league'])
    git_push('img ' + g['id'], [path])
    r = web({'action': 'post', 'title': title_for(f), 'html': build_html(g, f, ai, REPO_RAW + path), 'labels': labels_for(f)})
    print('Published:', r.get('url'))
    state['games'][g['id']] = {'post': r['id'], 'url': r['url'], 'league': g['league'], 'ko': g['ko'].isoformat(),
                              'date': ko.strftime('%Y-%m-%d'), 'score': g['score'], 'title': title_for(f), 'img': path,
                              'line1': line1, 'tv': g['tv'], 'fb': False, 'final': False,
                              'away': f['away']['short'], 'home': f['home']['short'], 'lname': f['league']}
    day = now.astimezone(ET).strftime('%Y-%m-%d')
    state['daily'][day] = state['daily'].get(day, 0) + 1


def add_results(state, now, limit=3):
    done = 0
    for gid, s in state['games'].items():
        if s.get('final') or done >= limit:
            continue
        ko = dt.datetime.fromisoformat(s['ko'])
        if now < ko + dt.timedelta(hours=2, minutes=45):
            continue
        try:
            j = get_json(ESPN + s['league'] + '/summary?event=' + gid)
            comp = j['header']['competitions'][0]
            if comp['status']['type'].get('state') != 'post':
                if now > ko + dt.timedelta(days=2):
                    s['final'] = True  # postponed/cancelled - stop checking
                continue
            t = {c['homeAway']: c for c in comp['competitors']}
            w = max(t.values(), key=lambda c: float(c.get('score') or 0))
            l = t['home'] if w is t['away'] else t['away']
            wn, ln = w['team'].get('displayName'), l['team'].get('displayName')
            detail = comp['status']['type'].get('detail', 'Final')
            tie = (w.get('score') == l.get('score'))
            line = (f"{wn} and {ln} tied {w.get('score')}-{l.get('score')}." if tie else
                    f"The {wn} beat the {ln} {w.get('score')}-{l.get('score')}.") if s['league'] != 'football/college-football' else \
                   (f"{wn} beat {ln} {w.get('score')}-{l.get('score')}." if not tie else f"{wn} and {ln} tied {w.get('score')}-{l.get('score')}.")
            box = (f'<div style="background:#fff2ec;border-left:5px solid #f2561d;border-radius:10px;padding:14px 16px;margin:0 0 18px">'
                   f'<b>FINAL ({esc(detail)}):</b> {esc(line)}</div>')
            # fetch current body from the public feed and insert the box after the live score
            post = get_json(f"https://www.blogger.com/feeds/{BLOG_ID}/posts/default/{s['post']}?alt=json")
            body = post['entry']['content']['$t']
            if 'FINAL (' not in body:
                body = body.replace('</div></div>', '</div></div>' + box, 1) if 'gtt-live' in body else box + body
                body = body.replace('the final score is added here after the game.', 'the final score is shown above.')
                labels = [c['term'] for c in post['entry'].get('category', [])] + ['Result']
                web({'action': 'update', 'postId': s['post'], 'html': body, 'labels': list(dict.fromkeys(labels))})
            s['final'] = True
            done += 1
            print('Result added:', line)
        except Exception as e:
            print('result fail', gid, e)


def send_fb(state, now):
    if not FB_HOOK:
        return
    day = now.astimezone(ET).strftime('%Y-%m-%d')
    if state['fbdaily'].get(day, 0) >= FB_DAILY_CAP:
        return
    pend = [(gid, s) for gid, s in state['games'].items() if not s.get('fb') and s.get('score', 0) >= 50
            and dt.timedelta(0) < dt.datetime.fromisoformat(s['ko']) - now <= dt.timedelta(hours=3)]
    if not pend:
        return
    gid, s = max(pend, key=lambda x: x[1]['score'])
    word = 'Tip-off' if s['lname'] == 'NBA' else 'Kickoff'
    tags = ' '.join('#' + re.sub(r'[^A-Za-z0-9]', '', x) for x in [s['away'], s['home'], s['lname']])
    cap = (f"{s['away']} vs {s['home']} \U0001F525\n{word}: {s['line1'].split('· ', 1)[-1].title().replace(' Et', ' ET')}"
           f"\nTV: {', '.join(s['tv'][:2]) or 'check local listings'}\n\nLive score, TV channel and preview: link in the comments \U0001F447\n\n{tags}")
    payload = {'photo': base64.b64encode(open(s['img'], 'rb').read()).decode(), 'filename': gid + '.jpg',
               'caption': cap, 'comment': 'Live score, TV channel and preview: ' + s['url'], 'link': s['url']}
    req = urllib.request.Request(FB_HOOK, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    print('FB:', urllib.request.urlopen(req, timeout=120).read().decode()[:100])
    s['fb'] = True
    state['fbdaily'][day] = state['fbdaily'].get(day, 0) + 1


def main():
    if not (WEBAPP and SECRET):
        sys.exit('WEBAPP / WEB_SECRET secrets missing')
    now = dt.datetime.now(dt.timezone.utc)
    state = load_state()
    try:
        add_results(state, now)
    except Exception as e:
        print('results error', e)
    try:
        send_fb(state, now)
    except Exception as e:
        print('fb error', e)
    day = now.astimezone(ET).strftime('%Y-%m-%d')
    if state['daily'].get(day, 0) < DAILY_CAP and os.environ.get('NO_POST') != '1':
        c = [g for g in candidates(now) if g['id'] not in state['games']
             and dt.timedelta(hours=3) <= g['ko'] - now <= dt.timedelta(hours=30) and g['score'] >= 20]
        c.sort(key=lambda g: (-(g['score'] + (40 if g['ko'] - now <= dt.timedelta(hours=12) else 0)), g['ko']))
        if c:
            try:
                publish_preview(c[0], state, now)
            except Exception as e:
                print('publish error', e)
        else:
            print('No game to preview right now.')
    save_state(state)


if __name__ == '__main__':
    main()
