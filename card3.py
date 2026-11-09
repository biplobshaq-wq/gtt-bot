"""Game Time Tonight thumbnail v3 (1200x675): star-player cut-outs, team colours, records,
division rank, kickoff, venue, TV. Player photos ONLY from Wikimedia Commons free licences
(CC BY / CC BY-SA / CC0 / PD) -> credit string returned for the caption/post."""
import io, json, re, urllib.parse, urllib.request, datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import numpy as np

W, H = 1200, 675
FB = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
UA = {'User-Agent': 'GameTimeTonightBot/1.0 (https://gametimetonight.blogspot.com)'}
OK_LIC = re.compile(r'^(CC BY(-SA)? [0-9.]+|CC0|Public domain)', re.I)
GOLD, WHITE, INK = (255, 197, 61), (255, 255, 255), (6, 12, 24)
import os
ANTON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts', 'Anton.ttf')
if not os.path.exists(ANTON): ANTON = FB
CUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'img', 'cut')


def _gj(u):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25).read())


def _hex(c, d=(40, 60, 90)):
    try: return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception: return d


def popularity(name):
    """30-day Wikipedia pageviews -> pick the real 'star' of each team."""
    try:
        end = datetime.date.today() - datetime.timedelta(days=1); st = end - datetime.timedelta(days=30)
        u = ('https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/'
             + urllib.parse.quote(name.replace(' ', '_')) + f'/daily/{st:%Y%m%d}/{end:%Y%m%d}')
        return sum(i['views'] for i in _gj(u)['items'])
    except Exception:
        return 0


def _file_ok(ftitle, name, nick):
    """Commons file -> (url, credit) if free licence AND it is clearly this player in this team."""
    m = _gj('https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode(
        {'action': 'query', 'titles': ftitle, 'prop': 'imageinfo|categories', 'cllimit': 50,
         'iiprop': 'extmetadata|url|size', 'iiurlwidth': 1100, 'format': 'json'}))
    p = list(m['query']['pages'].values())[0]
    if 'imageinfo' not in p: return None
    ii = p['imageinfo'][0]; em = ii.get('extmetadata', {})
    lic = (em.get('LicenseShortName') or {}).get('value', '').strip()
    if not OK_LIC.match(lic) or re.search(r'\b(NC|ND)\b', lic): return None
    if min(ii.get('width', 0), ii.get('height', 0)) < 450: return None
    txt = ' '.join([ftitle, re.sub(r'<[^>]+>', ' ', (em.get('ImageDescription') or {}).get('value', '')),
                    (em.get('Categories') or {}).get('value', ''), ' '.join(c['title'] for c in p.get('categories', []))]).lower()
    last = name.split()[-1].lower() if not re.search(r'(jr\.|sr\.|ii|iii)$', name.lower()) else name.split()[-2].lower()
    if last not in txt: return None
    if nick and nick.lower() not in txt: return None   # must show the CURRENT team
    art = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', (em.get('Artist') or {}).get('value', ''))).strip()[:40] or 'Wikimedia Commons'
    return ii.get('thumburl') or ii['url'], f'{name}: {art} ({lic}) via Wikimedia Commons'


def free_photo(name, kw='football', nick=''):
    """-> (PIL image, credit). Commons free licence only; photo must be tagged with the player's current team."""
    files = []
    try:
        q = _gj('https://en.wikipedia.org/w/api.php?' + urllib.parse.urlencode(
            {'action': 'query', 'titles': name, 'prop': 'pageimages|description', 'piprop': 'name', 'redirects': 1, 'format': 'json'}))
        pg = list(q['query']['pages'].values())[0]
        if kw in (pg.get('description') or '').lower() and pg.get('pageimage'):
            files.append('File:' + pg['pageimage'])
    except Exception:
        pass
    try:
        q = _gj('https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode(
            {'action': 'query', 'list': 'search', 'srsearch': f'"{name}" {nick} filetype:bitmap', 'srnamespace': 6, 'srlimit': 8, 'format': 'json'}))
        files += [x['title'] for x in q['query']['search'] if x['title'] not in files]
    except Exception:
        pass
    for ft in files[:8]:
        try:
            r = _file_ok(ft, name, nick)
            if not r: continue
            raw = urllib.request.urlopen(urllib.request.Request(r[0], headers=UA), timeout=30).read()
            return Image.open(io.BytesIO(raw)).convert('RGB'), r[1]
        except Exception:
            continue
    return None


_sess = None
def cutout(im):
    """background removal (rembg u2net_human_seg); returns RGBA trimmed to the person."""
    global _sess
    from rembg import remove, new_session
    if _sess is None: _sess = new_session('u2net_human_seg')
    out = remove(im, session=_sess, post_process_mask=True)
    arr = np.array(out); a = arr[:, :, 3]
    from scipy import ndimage
    lab, n = ndimage.label(a > 40)
    if n > 1:  # keep only the biggest person (drop teammates in the background)
        sizes = ndimage.sum(np.ones_like(a), lab, range(1, n + 1)); keep = int(np.argmax(sizes)) + 1
        arr[:, :, 3] = np.where(lab == keep, a, 0); out = Image.fromarray(arr); a = arr[:, :, 3]
    ys, xs = np.where(a > 40)
    if len(xs) < 100: return None
    if (xs.max() - xs.min()) > 1.05 * (ys.max() - ys.min()): return None  # group shot / not a single player
    return out.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


def jersey_ok(co, team_cols):
    """True if the torso colour matches the team colours (or is white/black alt jersey)."""
    import colorsys
    a = np.array(co.convert('RGBA')); h, w = a.shape[:2]
    reg = a[int(h * .45):int(h * .8), int(w * .25):int(w * .75)]
    px = reg[reg[:, :, 3] > 200][:, :3]
    if len(px) < 200: return True
    hsv = np.array([colorsys.rgb_to_hsv(*(p / 255.0)) for p in px[::max(1, len(px) // 3000)]])
    sat = hsv[(hsv[:, 1] > .35) & (hsv[:, 2] > .2)]
    if len(sat) < .25 * len(hsv): return True  # mostly white / grey / black jersey -> neutral
    hues = np.histogram(sat[:, 0], bins=24, range=(0, 1))[0]; hj = (np.argmax(hues) + .5) / 24
    for c in team_cols:
        r, g, b = _hex(c, (128, 128, 128)); th, ts, tv = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if ts < .25: continue
        dh = min(abs(hj - th), 1 - abs(hj - th))
        if dh < 0.04: return True
    return False


def _logo(url, size):
    try:
        im = Image.open(io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=25).read())).convert('RGBA')
        im.thumbnail((size, size)); return im
    except Exception:
        return None


def _fit(d, text, path, maxw, start, minsize=20):
    s = start
    while s > minsize and d.textlength(text, font=ImageFont.truetype(path, s)) > maxw: s -= 2
    return ImageFont.truetype(path, s)


def _glow_paste(base, fg, xy, color, radius=18, strength=170):
    a = fg.split()[3]
    g = Image.new('RGBA', fg.size, color + (0,)); g.putalpha(a.point(lambda v: min(255, v) * strength // 255))
    pad = radius * 3
    big = Image.new('RGBA', (fg.width + 2 * pad, fg.height + 2 * pad), (0, 0, 0, 0)); big.paste(g, (pad, pad), g)
    big = big.filter(ImageFilter.GaussianBlur(radius))
    base.alpha_composite(big, (xy[0] - pad, xy[1] - pad)); base.alpha_composite(fg, xy)


def make_thumb(g, out, bg_path=None):
    """g = dict(league, headline, away{name,short,abbr,logo,color,record,rank}, home{...},
                ko_text, venue, tv, players{away:(name,stat), home:(name,stat)})"""
    ca, ch = _hex(g['away'].get('color')), _hex(g['home'].get('color'))
    if bg_path:
        b = Image.open(bg_path).convert('RGB'); b = ImageOps.fit(b, (W, H), Image.LANCZOS, centering=(0.5, 0.45))
        im = b.convert('RGBA')
    else:
        im = Image.new('RGBA', (W, H), INK + (255,))
    im = Image.alpha_composite(im, Image.new('RGBA', (W, H), (0, 0, 0, 120)))
    t = Image.new('RGBA', (W, H), (0, 0, 0, 0)); td = ImageDraw.Draw(t)
    td.polygon([(0, 0), (640, 0), (560, H), (0, H)], fill=ca + (150,))
    td.polygon([(640, 0), (W, 0), (W, H), (560, H)], fill=ch + (150,))
    im = Image.alpha_composite(im, t)
    # light rays behind players
    rays = Image.new('RGBA', (W, H), (0, 0, 0, 0)); rd = ImageDraw.Draw(rays)
    for cx in (230, 970):
        rd.ellipse((cx - 300, 60, cx + 300, 660), fill=(255, 255, 255, 40))
    im = Image.alpha_composite(im, rays.filter(ImageFilter.GaussianBlur(60)))
    credits = []
    for side, cx, col in (('away', 245, ca), ('home', 955, ch)):
        cands = (g.get('cands') or {}).get(side) or ([g['players'][side]] if (g.get('players') or {}).get(side) else [])
        placed = False
        for pl in cands[:3]:
            ph = free_photo(pl[0], 'basketball' if g['league'] == 'NBA' else 'football', g[side].get('nick', ''))
            if ph:
                slug = re.sub(r'[^a-z0-9]+', '-', pl[0].lower()).strip('-')
                cp = os.path.join(CUT_DIR, slug + '.png')
                try:
                    if os.path.exists(cp):
                        co = Image.open(cp).convert('RGBA')
                    else:
                        co = cutout(ph[0])
                        if co is not None:
                            co.thumbnail((640, 640), Image.LANCZOS); os.makedirs(CUT_DIR, exist_ok=True); co.save(cp, optimize=True)
                except Exception as e:
                    print('cutout error', e); co = None
                if co is not None and not jersey_ok(co, [g[side].get('color'), g[side].get('alt')]):
                    print('jersey mismatch, skip', pl[0]); co = None
                if co is not None:
                    g.setdefault('players', {})[side] = pl
                    sc = 600 / co.height; co = co.resize((int(co.width * sc), 600), Image.LANCZOS)
                    if co.width > 520: co = co.crop(((co.width - 520) // 2, 0, (co.width + 520) // 2, co.height))
                    if side == 'home': co = ImageOps.mirror(co) if g.get('mirror_home') else co
                    _glow_paste(im, co, (cx - co.width // 2, H - 600 - 70), (255, 255, 255), 14, 150)
                    credits.append(ph[1]); placed = True; break
        lg = _logo(g[side].get('logo', ''), 105 if placed else 300)
        if lg:
            if placed:
                x = (515 - lg.width) if side == 'away' else 685; y = 215
            else:
                x = cx - lg.width // 2; y = 150
            _glow_paste(im, lg, (x, y), (0, 0, 0), 10, 140)
    d = ImageDraw.Draw(im, 'RGBA')
    # top strip: brand + league + headline
    d.rectangle((0, 0, W, 70), fill=INK + (235,))
    fbz = ImageFont.truetype(ANTON, 34)
    d.text((26, 14), 'GAME TIME', font=fbz, fill=WHITE); d.text((26 + d.textlength('GAME TIME ', font=fbz), 14), 'TONIGHT', font=fbz, fill=(242, 86, 29))
    hl = g.get('headline', g['league']).upper()
    fh = _fit(d, hl, ANTON, 560, 36); tw = d.textlength(hl, font=fh)
    d.rounded_rectangle((W - tw - 60, 12, W - 22, 58), 22, fill=(242, 86, 29)); d.text((W - tw - 41, 15), hl, font=fh, fill=WHITE)
    # centre VS
    vs = Image.new('RGBA', (W, H), (0, 0, 0, 0)); vd = ImageDraw.Draw(vs)
    fv = ImageFont.truetype(ANTON, 150); w_ = vd.textlength('VS', font=fv)
    vd.text((600 - w_ / 2 + 5, 170 + 6), 'VS', font=fv, fill=(0, 0, 0, 200))
    im = Image.alpha_composite(im, vs.filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(im, 'RGBA'); d.text((600 - w_ / 2, 170), 'VS', font=fv, fill=GOLD, stroke_width=4, stroke_fill=INK)
    # kickoff badge under VS
    ko = g.get('ko_text', '').upper()
    fk = _fit(d, ko, ANTON, 330, 40); kw_ = d.textlength(ko, font=fk)
    d.rounded_rectangle((600 - kw_ / 2 - 18, 372, 600 + kw_ / 2 + 18, 428), 12, fill=WHITE)
    d.text((600 - kw_ / 2, 376), ko, font=fk, fill=INK)
    # name plates + record + rank
    for side, x0, col in (('away', 20, ca), ('home', 700, ch)):
        tm = g[side]; pl = (g.get('players') or {}).get(side)
        nm = (pl[0] if pl else tm['short']).upper()
        d.rectangle((x0, 470, x0 + 480, 528), fill=col + (245,))
        fn = _fit(d, nm, ANTON, 450, 44); d.text((x0 + 240 - d.textlength(nm, font=fn) / 2, 474), nm, font=fn, fill=WHITE, stroke_width=2, stroke_fill=INK)
        sub = ' • '.join(x for x in [tm['short'].upper() if pl else '', tm.get('record', ''), tm.get('rank', '').upper()] if x)
        d.rectangle((x0, 528, x0 + 480, 566), fill=INK + (235,))
        fs = _fit(d, sub, FB, 460, 24, 12); d.text((x0 + 240 - d.textlength(sub, font=fs) / 2, 534), sub, font=fs, fill=GOLD)
    # bottom bar venue + tv
    d.rectangle((0, H - 72, W, H), fill=INK + (240,))
    bl = '  |  '.join(x for x in [g.get('venue', ''), ('TV: ' + g['tv']) if g.get('tv') else ''] if x).upper()
    fb_ = _fit(d, bl, FB, W - 60, 28); d.text(((W - d.textlength(bl, font=fb_)) / 2, H - 52), bl, font=fb_, fill=WHITE)
    im.convert('RGB').save(out, 'JPEG', quality=88, optimize=True)
    return out, credits
