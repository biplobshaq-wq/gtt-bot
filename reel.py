"""12-second vertical Reel (1080x1920) for a game: our own animated design + team logos."""
import io, math, shutil, subprocess, urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS, DUR = 1080, 1920, 30, 12.0
FB = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FR = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
NAVY, ORANGE, GOLD, WHITE = (10, 20, 38), (242, 86, 29), (255, 197, 61), (255, 255, 255)


def _hex(c, d=(40, 60, 90)):
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return d


def _logo(url, size):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30).read()
        im = Image.open(io.BytesIO(raw)).convert('RGBA')
        im.thumbnail((size, size))
        return im
    except Exception:
        return None


def _fit(text, path, maxw, start, minsize=30):
    s = start
    while s > minsize and ImageFont.truetype(path, s).getlength(text) > maxw:
        s -= 2
    return ImageFont.truetype(path, s)


def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def make_reel(away, home, league, dayline, timeline, tvline, out):
    ca, ch = _hex(away.get('color', '')), _hex(home.get('color', ''))
    la, lh = _logo(away.get('logo', ''), 300), _logo(home.get('logo', ''), 300)
    # static background: two team colour halves split diagonally, darkened
    bg = Image.new('RGBA', (W, H), NAVY + (255,))
    d = ImageDraw.Draw(bg)
    d.polygon([(0, 0), (W, 0), (W, 700), (0, 1100)], fill=ca + (255,))
    d.polygon([(0, 1100), (W, 700), (W, H), (0, H)], fill=ch + (255,))
    bg = Image.alpha_composite(bg, Image.new('RGBA', (W, H), (6, 12, 26, 165)))
    d = ImageDraw.Draw(bg)
    d.line([(0, 1100), (W, 700)], fill=GOLD + (255,), width=8)
    fa = _fit(away['name'].upper(), FB, W - 140, 84, 46)
    fh = _fit(home['name'].upper(), FB, W - 140, 84, 46)
    fday = _fit(dayline, FB, W - 140, 64, 36)
    ftime = _fit(timeline, FB, W - 200, 70, 40)
    ftv = _fit(tvline, FR, W - 140, 50, 32)
    fl = ImageFont.truetype(FB, 40)

    def logo_disc(im, logo, cx, cy, a, r=210):
        if a <= 0:
            return
        rr = int(r * (0.6 + 0.4 * a))
        disc = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        dd = ImageDraw.Draw(disc)
        dd.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(255, 255, 255, int(240 * a)))
        im.alpha_composite(disc)
        if logo:
            s = int(logo.width * (0.6 + 0.4 * a)), int(logo.height * (0.6 + 0.4 * a))
            lg = logo.resize(s)
            if a < 1:
                al = lg.split()[3].point(lambda p: int(p * a))
                lg.putalpha(al)
            im.alpha_composite(lg, (cx - s[0] // 2, cy - s[1] // 2))

    def frame(t):
        im = bg.copy()
        d = ImageDraw.Draw(im, 'RGBA')
        # header
        d.rounded_rectangle((60, 80, W - 60, 180), 30, fill=(6, 12, 24, 230), outline=ORANGE, width=4)
        hf = ImageFont.truetype(FB, 46)
        a1, a2 = 'GAME TIME ', 'TONIGHT'
        x0 = (W - hf.getlength(a1 + a2)) / 2
        d.text((x0, 104), a1, font=hf, fill=WHITE)
        d.text((x0 + hf.getlength(a1), 104), a2, font=hf, fill=ORANGE)
        tw = fl.getlength(league.upper())
        d.rounded_rectangle(((W - tw) / 2 - 30, 210, (W + tw) / 2 + 30, 275), 32, fill=ORANGE)
        d.text(((W - tw) / 2, 220), league.upper(), font=fl, fill=WHITE)
        # away team (top)
        a = _ease((t - 0.2) / 0.7)
        logo_disc(im, la, W // 2, 560, a)
        d = ImageDraw.Draw(im, 'RGBA')
        if a > 0:
            n = away['name'].upper()
            d.text(((W - fa.getlength(n)) / 2, 800 + (1 - a) * 40), n, font=fa, fill=WHITE + (int(255 * a),))
        # VS
        a = _ease((t - 0.9) / 0.4)
        if a > 0:
            p = 1 + 0.06 * math.sin(t * 5)
            r = int(70 * p * a)
            d.ellipse((W // 2 - r, 960 - r, W // 2 + r, 960 + r), fill=(6, 12, 24, 245), outline=GOLD, width=5)
            vf = ImageFont.truetype(FB, int(52 * p * a) + 1)
            d.text((W / 2 - vf.getlength('VS') / 2, 960 - vf.size * 0.62), 'VS', font=vf, fill=GOLD)
        # home team (bottom)
        a = _ease((t - 1.2) / 0.7)
        logo_disc(im, lh, W // 2, 1270, a)
        d = ImageDraw.Draw(im, 'RGBA')
        if a > 0:
            n = home['name'].upper()
            d.text(((W - fh.getlength(n)) / 2, 1505 + (1 - a) * 40), n, font=fh, fill=WHITE + (int(255 * a),))
        # info panel then CTA (bottom area)
        y = 1620
        if t < 7.5:
            a = _ease((t - 2.2) / 0.6) * (1 - _ease((t - 7.0) / 0.5))
            if a > 0:
                d.rounded_rectangle((50, y, W - 50, H - 70), 36, fill=(6, 12, 24, int(235 * a)))
                d.text(((W - fday.getlength(dayline)) / 2, y + 22), dayline, font=fday, fill=GOLD + (int(255 * a),))
                d.text(((W - ftime.getlength(timeline)) / 2, y + 22 + fday.size + 12), timeline, font=ftime, fill=WHITE + (int(255 * a),))
        else:
            a = _ease((t - 7.5) / 0.6)
            p = 1 + 0.02 * math.sin((t - 7.5) * 6)
            bx0, bx1 = int(50 + (1 - p) * 300), int(W - 50 - (1 - p) * 300)
            d.rounded_rectangle((bx0, y, bx1, H - 70), 36, fill=GOLD + (int(250 * a),))
            l1, l2 = 'Live score + where to watch', 'Link in the comments \u2193'
            f1 = _fit(l1, FB, W - 180, 50, 30)
            f2 = _fit(l2, FB, W - 180, 62, 34)
            d.text(((W - f1.getlength(l1)) / 2, y + 26), l1, font=f1, fill=NAVY + (int(255 * a),))
            d.text(((W - f2.getlength(l2)) / 2, y + 26 + f1.size + 14), l2, font=f2, fill=NAVY + (int(255 * a),))
        # TV line under header (from 3s)
        a = _ease((t - 3.0) / 0.5)
        if a > 0:
            d.text(((W - ftv.getlength(tvline)) / 2, 300), tvline, font=ftv, fill=WHITE + (int(235 * a),))
        return im.convert('RGB')

    ff = shutil.which('ffmpeg')
    if not ff:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS),
           '-i', '-', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo', '-shortest',
           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'veryfast', '-crf', '24',
           '-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart', out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(int(DUR * FPS)):
        p.stdin.write(frame(i / FPS).tobytes())
    p.stdin.close()
    p.wait()
    return out
