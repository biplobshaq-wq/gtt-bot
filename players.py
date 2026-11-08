"""Free-licensed player photos from Wikimedia Commons (CC BY / CC BY-SA / CC0 / Public domain only).
Returns a square face-centred crop + an attribution credit. Fair-use / unlicensed images are skipped."""
import io, json, re, urllib.parse, urllib.request
from PIL import Image

UA = {'User-Agent': 'GameTimeTonightBot/1.0 (https://gametimetonight.blogspot.com)'}
OK_LIC = re.compile(r'^(CC BY(-SA)? [0-9.]+|CC0|Public domain)', re.I)


def _gj(u):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20).read())


def _page(title):
    q = _gj('https://en.wikipedia.org/w/api.php?' + urllib.parse.urlencode(
        {'action': 'query', 'titles': title, 'prop': 'pageimages|description', 'piprop': 'name',
         'redirects': 1, 'format': 'json'}))
    return list(q['query']['pages'].values())[0]


def _face_crop(im, size=420):
    w, h = im.size
    box = None
    try:
        import cv2, numpy as np
        g = cv2.cvtColor(np.array(im.convert('RGB')), cv2.COLOR_RGB2GRAY)
        cc = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        faces = cc.detectMultiScale(g, 1.1, 5, minSize=(max(24, w // 20), max(24, w // 20)))
        if len(faces):
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            side = int(max(fw, fh) * 2.6)
            side = min(side, w, h)
            cx, cy = x + fw / 2, y + fh / 2 + fh * 0.25
            l = int(min(max(0, cx - side / 2), w - side)); t = int(min(max(0, cy - side / 2), h - side))
            box = (l, t, l + side, t + side)
    except Exception:
        box = None
    if not box:
        side = min(w, h)
        l = (w - side) // 2
        t = 0 if h > w else (h - side) // 2
        box = (l, t, l + side, t + side)
    return im.crop(box).resize((size, size), Image.LANCZOS)


def get_photo(name, sport='football'):
    """-> (PIL.Image RGBA square, 'Artist (LICENSE)') or None"""
    kw = 'basketball' if sport == 'basketball' else 'football'
    for title in (name, name + (' (basketball)' if kw == 'basketball' else ' (American football)')):
        try:
            pg = _page(title)
        except Exception:
            continue
        if kw not in (pg.get('description') or '').lower() or not pg.get('pageimage'):
            continue
        try:
            m = _gj('https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode(
                {'action': 'query', 'titles': 'File:' + pg['pageimage'], 'prop': 'imageinfo',
                 'iiprop': 'extmetadata|url', 'iiurlwidth': 900, 'format': 'json'}))
            p = list(m['query']['pages'].values())[0]
            if 'imageinfo' not in p:
                return None  # local (fair-use) image -> not allowed
            ii = p['imageinfo'][0]
            em = ii.get('extmetadata', {})
            lic = (em.get('LicenseShortName') or {}).get('value', '').strip()
            if not OK_LIC.match(lic) or re.search(r'\b(NC|ND)\b', lic):
                return None
            art = re.sub(r'<[^>]+>', '', (em.get('Artist') or {}).get('value', '')).strip()
            art = re.sub(r'\s+', ' ', art)[:40] or 'Wikimedia Commons'
            raw = urllib.request.urlopen(urllib.request.Request(ii.get('thumburl') or ii['url'], headers=UA), timeout=30).read()
            im = Image.open(io.BytesIO(raw)).convert('RGB')
            return _face_crop(im), f'{art} ({lic})'
        except Exception:
            return None
    return None
