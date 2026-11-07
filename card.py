"""Matchup card image 1200x675 (our own design + team logos)."""
import io, urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageFilter
W, H = 1200, 675
FB = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FR = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
NAVY, ORANGE, GOLD = (10, 20, 38), (242, 86, 29), (255, 197, 61)

def _hex(c, d=(40, 60, 90)):
    try: return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))
    except Exception: return d

def _logo(url, size):
    try:
        im = Image.open(io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30).read())).convert('RGBA')
        im.thumbnail((size, size)); return im
    except Exception:
        return None

def _fit(d, text, path, maxw, start, minsize=26):
    s = start
    while s > minsize and d.textlength(text, font=ImageFont.truetype(path, s)) > maxw: s -= 2
    return ImageFont.truetype(path, s)

def make_card(away, home, line1, line2, out, league=''):
    """away/home: dict(name, abbr, logo, color)."""
    im = Image.new('RGB', (W, H), NAVY)
    d = ImageDraw.Draw(im, 'RGBA')
    ca, ch = _hex(away.get('color', '')), _hex(home.get('color', ''))
    # diagonal team colour halves
    d.polygon([(0, 0), (650, 0), (550, H), (0, H)], fill=ca + (255,))
    d.polygon([(650, 0), (W, 0), (W, H), (550, H)], fill=ch + (255,))
    im = Image.alpha_composite(im.convert('RGBA'), Image.new('RGBA', (W, H), (8, 14, 28, 150)))
    d = ImageDraw.Draw(im, 'RGBA')
    d.line([(650, 0), (550, H)], fill=GOLD + (255,), width=6)
    # top strip
    d.rectangle((0, 0, W, 64), fill=(6, 12, 24, 235))
    f = ImageFont.truetype(FB, 30)
    d.text((32, 15), 'GAME TIME', font=f, fill=(255, 255, 255)); d.text((32 + d.textlength('GAME TIME ', font=f), 15), 'TONIGHT', font=f, fill=ORANGE)
    if league:
        fl = ImageFont.truetype(FB, 26); tw = d.textlength(league.upper(), font=fl)
        d.rounded_rectangle((W - tw - 64, 12, W - 24, 52), 20, fill=ORANGE); d.text((W - tw - 44, 17), league.upper(), font=fl, fill=(255, 255, 255))
    for t, cx in ((away, 300), (home, 900)):
        d.ellipse((cx - 140, 85, cx + 140, 365), fill=(255, 255, 255, 235))
        lg = _logo(t.get('logo', ''), 200)
        if lg:
            sh = Image.new('RGBA', (W, H), (0, 0, 0, 0)); sh.paste((0, 0, 0, 60), (cx - lg.width // 2 + 4, 125 + (200 - lg.height) // 2 + 4), lg)
            im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(8)))
            im.paste(lg, (cx - lg.width // 2, 125 + (200 - lg.height) // 2), lg)
        d = ImageDraw.Draw(im, 'RGBA')
        fn = _fit(d, t['name'].upper(), FB, 480, 44)
        d.text((cx - d.textlength(t['name'].upper(), font=fn) / 2, 395), t['name'].upper(), font=fn, fill=(255, 255, 255))
    d.ellipse((550, 190, 650, 290), fill=(6, 12, 24, 240), outline=GOLD, width=4)
    fv = ImageFont.truetype(FB, 38); d.text((600 - d.textlength('VS', font=fv) / 2, 216), 'VS', font=fv, fill=GOLD)
    d.rectangle((0, H - 200, W, H), fill=(6, 12, 24, 225))
    f1 = _fit(d, line1, FB, W - 80, 50); d.text(((W - d.textlength(line1, font=f1)) / 2, H - 170), line1, font=f1, fill=GOLD)
    f2 = _fit(d, line2, FR, W - 80, 36); d.text(((W - d.textlength(line2, font=f2)) / 2, H - 92), line2, font=f2, fill=(235, 240, 250))
    im.convert('RGB').save(out, 'JPEG', quality=86, optimize=True)
    return out
