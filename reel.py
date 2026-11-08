"""12-second vertical Reel (1080x1920) v2: sport stadium background (our own AI art), slow zoom,
team logos sliding in, rank/record, countdown hook, 'who wins?' question, original synthesized beat."""
import io, math, os, random, shutil, subprocess, urllib.request, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS, DUR = 1080, 1920, 30, 15.0
HERE = os.path.dirname(os.path.abspath(__file__))
FB = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FR = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
NAVY, ORANGE, GOLD, WHITE = (10, 20, 38), (242, 86, 29), (255, 197, 61), (255, 255, 255)
SR = 44100


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


def pick_bg(league, seed):
    sport = 'basketball' if 'NBA' in league.upper() or 'BASKET' in league.upper() else 'football'
    d = os.path.join(HERE, 'bg')
    files = sorted(f for f in os.listdir(d) if f.startswith(sport))
    return os.path.join(d, files[int(seed) % len(files)]) if files else None


# ------------------------------------------------------------------ audio (original, synthesized)
def _beat(path, dur=DUR, impacts=(0.2, 1.6, 2.0, 2.5, 7.0, 10.5)):
    n = int(SR * dur)
    t = np.arange(n) / SR
    out = np.zeros(n)
    bpm = 120.0
    step = 60.0 / bpm / 2  # eighth notes
    rng = np.random.default_rng(7)
    for k in range(int(dur / step)):
        s0 = int(k * step * SR)
        beat = k % 8
        if beat in (0, 3, 4) and s0 + int(0.25 * SR) <= n:  # kick
            L = int(0.25 * SR); tt = np.arange(L) / SR
            f = 120 * np.exp(-tt * 25) + 45
            out[s0:s0 + L] += 0.9 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 9)
        if beat in (2, 6) and s0 + int(0.2 * SR) <= n:  # clap/snare
            L = int(0.2 * SR); tt = np.arange(L) / SR
            out[s0:s0 + L] += 0.35 * rng.standard_normal(L) * np.exp(-tt * 22)
        if s0 + int(0.05 * SR) <= n:  # hi-hat
            L = int(0.05 * SR); tt = np.arange(L) / SR
            hh = rng.standard_normal(L); hh = np.diff(np.concatenate([[0], hh]))
            out[s0:s0 + L] += 0.10 * hh * np.exp(-tt * 80)
    # bass line
    notes = [55.0, 55.0, 65.4, 49.0]
    bar = step * 8
    for b in range(int(dur / bar) + 1):
        f = notes[b % 4]
        s0, s1 = int(b * bar * SR), min(n, int((b + 1) * bar * SR))
        tt = np.arange(s1 - s0) / SR
        out[s0:s1] += 0.22 * np.sign(np.sin(2 * np.pi * f * tt)) * (0.6 + 0.4 * np.exp(-(tt % step) * 6))
    # whoosh + impact hits
    for ti in impacts:
        s0 = int(ti * SR); L = int(0.5 * SR)
        if s0 + L > n:
            continue
        tt = np.arange(L) / SR
        out[s0:s0 + L] += 0.5 * np.sin(2 * np.pi * (60 * np.exp(-tt * 6) + 30) * tt) * np.exp(-tt * 5)
        w0 = max(0, s0 - int(0.35 * SR))
        wl = s0 - w0
        if wl > 0:
            out[w0:s0] += 0.18 * rng.standard_normal(wl) * np.linspace(0, 1, wl) ** 2
    # fade in/out, normalise
    fade = int(0.4 * SR)
    out[:fade] *= np.linspace(0, 1, fade); out[-fade * 2:] *= np.linspace(1, 0, fade * 2)
    out = np.tanh(out * 1.2)
    out = (out / (np.abs(out).max() + 1e-9) * 0.8 * 32767).astype(np.int16)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(out.tobytes())
    return path


# ------------------------------------------------------------------ video
def make_reel(away, home, league, dayline, timeline, tvline, out, hook='GAME DAY', seed=0, preview=None, players=None):
    """away/home: dict(name, logo, color, rank, record). hook: big first-second text e.g. 'KICKOFF IN 2 HOURS'."""
    ca, ch = _hex(away.get('color', '')), _hex(home.get('color', ''))
    la, lh = _logo(away.get('logo', ''), 270), _logo(home.get('logo', ''), 270)
    bgp = pick_bg(league, seed)
    if bgp:
        base = Image.open(bgp).convert('RGB')
        sc = max(W / base.width, H / base.height) * 1.14
        base = base.resize((int(base.width * sc), int(base.height * sc)), Image.LANCZOS)
    else:
        base = Image.new('RGB', (int(W * 1.14), int(H * 1.14)), NAVY)
    # overlay: darken + team colour glows top/bottom + dark bands for text
    ov = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for y in range(H):
        a = 95
        if y < 420: a = int(120 + 110 * (1 - y / 420))
        if y > H - 520: a = int(120 + 120 * ((y - (H - 520)) / 520))
        od.line([(0, y), (W, y)], fill=(4, 8, 18, a))
    glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-200, 360, W + 200, 900), fill=ca + (110,))
    gd.ellipse((-200, 980, W + 200, 1540), fill=ch + (110,))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    ov = Image.alpha_composite(glow, ov)

    fa = _fit(away['name'].upper(), FB, W - 160, 80, 44)
    fh = _fit(home['name'].upper(), FB, W - 160, 80, 44)
    fsub = ImageFont.truetype(FB, 40)
    fday = _fit(dayline, FB, W - 160, 58, 34)
    ftime = _fit(timeline, FB, W - 160, 76, 40)
    ftv = _fit(tvline, FR, W - 160, 44, 28)
    fl = ImageFont.truetype(FB, 38)
    fhook = _fit(hook.upper(), FB, W - 120, 120, 50)
    fpt = ImageFont.truetype(FB, 42)
    pl = []
    for it in (players or [])[:2]:
        n, st, c = it[0], it[1], it[2]
        ph = it[3] if len(it) > 3 else None
        cr = it[4] if len(it) > 4 else ''
        if n:
            pl.append((n, st, _hex(c) if isinstance(c, str) else c, ph, cr))
    players = pl
    logos_by_col = [la, lh]
    pcirc = []
    for k, p_ in enumerate(players):
        r = 200
        src = p_[3] if p_[3] is not None else None
        if src is None:
            src = Image.new('RGBA', (2 * r, 2 * r), (255, 255, 255, 255))
            lg = logos_by_col[k] if k < 2 else None
            if lg:
                lg2 = lg.copy(); lg2.thumbnail((int(r * 1.3), int(r * 1.3)))
                src.alpha_composite(lg2, (r - lg2.width // 2, r - lg2.height // 2))
        src = src.convert('RGBA').resize((2 * r, 2 * r), Image.LANCZOS)
        m = Image.new('L', (2 * r, 2 * r), 0); ImageDraw.Draw(m).ellipse((0, 0, 2 * r - 1, 2 * r - 1), fill=255)
        src.putalpha(m)
        pcirc.append(src)
    credits = ' \u00b7 '.join(p_[4] for p_ in players if p_[3] is not None and p_[4])
    fcred = _fit('Photos: ' + credits + ' / Wikimedia Commons', FR, W - 140, 24, 16) if credits else None
    fpn = ImageFont.truetype(FB, 46)
    fps = ImageFont.truetype(FB, 36)

    def scene(im, t):
        sc = _ease((t - 6.8) / 0.4) * (1 - _ease((t - 10.2) / 0.4))
        if sc <= 0:
            return im
        lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        dl = ImageDraw.Draw(lay)
        dl.rounded_rectangle((36, 300, W - 36, 1590), 44, fill=(6, 12, 24, int(250 * sc)), outline=GOLD + (int(255 * sc),), width=5)
        ttl = 'PLAYERS TO WATCH'
        dl.text(((W - fpt.getlength(ttl)) / 2, 400), ttl, font=fpt, fill=GOLD + (int(255 * sc),))
        n = len(players)
        cols = [W // 2] if n == 1 else [W // 4 + 20, 3 * W // 4 - 20]
        for k, (nm, st, col, ph, cr) in enumerate(players):
            ak = _ease((t - 7.0 - 0.3 * k) / 0.45) * sc
            if ak <= 0:
                continue
            cx, cy, r = cols[k], 790, 200
            rr = int(r * (0.7 + 0.3 * ak))
            dl.ellipse((cx - rr - 14, cy - rr - 14, cx + rr + 14, cy + rr + 14), fill=col + (int(255 * ak),))
            pc = pcirc[k].resize((2 * rr, 2 * rr), Image.BILINEAR)
            if ak < 1:
                pc.putalpha(pc.split()[3].point(lambda v: int(v * ak)))
            lay.alpha_composite(pc, (cx - rr, cy - rr))
            dl = ImageDraw.Draw(lay)
            fn = _fit(nm, FB, W // 2 - 60, 46, 26)
            dl.text((cx - fn.getlength(nm) / 2, 1050), nm, font=fn, fill=WHITE + (int(255 * ak),))
            if st:
                fs = _fit(st, FB, W // 2 - 60, 36, 22)
                dl.text((cx - fs.getlength(st) / 2, 1115), st, font=fs, fill=GOLD + (int(255 * ak),))
        tn = (away['name'].upper(), home['name'].upper())
        for k in range(min(n, 2)):
            ak = _ease((t - 7.3 - 0.3 * k) / 0.45) * sc
            if ak > 0:
                f = _fit(tn[k], FR, W // 2 - 80, 32, 20)
                dl.text((cols[k] - f.getlength(tn[k]) / 2, 1170), tn[k], font=f, fill=(200, 210, 230, int(255 * ak)))
        if n == 2:
            a2 = _ease((t - 7.6) / 0.3) * sc
            dl.ellipse((W // 2 - 56, 790 - 56, W // 2 + 56, 790 + 56), fill=(6, 12, 24, int(250 * a2)), outline=GOLD + (int(255 * a2),), width=5)
            vf = ImageFont.truetype(FB, 42)
            dl.text((W / 2 - vf.getlength('VS') / 2, 790 - 26), 'VS', font=vf, fill=GOLD + (int(255 * a2),))
        if fcred:
            line = 'Photos: ' + credits + ' / Wikimedia Commons'
            dl.text(((W - fcred.getlength(line)) / 2, 1530), line, font=fcred, fill=(170, 180, 200, int(230 * sc)))
        im.alpha_composite(lay)
        return im

    def sub(t):
        r = ('#%s  ' % t['rank']) if t.get('rank') and str(t.get('rank')) not in ('99', '0') else ''
        return (r + (t.get('record') or '')).strip()
    sa, sh = sub(away), sub(home)

    def disc(im, logo, cx, cy, a, col, r=190):
        if a <= 0:
            return
        layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        dd = ImageDraw.Draw(layer)
        rr = r + 26
        dd.ellipse((cx - rr - 20, cy - rr - 20, cx + rr + 20, cy + rr + 20), fill=col + (int(150 * a),))
        layer = layer.filter(ImageFilter.GaussianBlur(28))
        dd = ImageDraw.Draw(layer)
        dd.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=col + (int(255 * a),))
        dd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, int(250 * a)))
        im.alpha_composite(layer)
        if logo:
            lg = logo
            if a < 1:
                lg = logo.copy(); lg.putalpha(logo.split()[3].point(lambda p: int(p * a)))
            im.alpha_composite(lg, (cx - lg.width // 2, cy - lg.height // 2))

    def ctext(d, y, s, f, col):
        d.text(((W - f.getlength(s)) / 2, y), s, font=f, fill=col)

    def frame(t):
        z = 1 + 0.12 * (t / DUR)  # slow zoom (Ken Burns)
        cw, chh = int(W * 1.14 / z), int(H * 1.14 / z)
        bw, bh = base.size
        x0, y0 = (bw - cw) // 2, (bh - chh) // 2
        im = base.crop((x0, y0, x0 + cw, y0 + chh)).resize((W, H), Image.BILINEAR).convert('RGBA')
        im.alpha_composite(ov)
        d = ImageDraw.Draw(im, 'RGBA')
        # header
        hf = ImageFont.truetype(FB, 44)
        a1, a2 = 'GAME TIME ', 'TONIGHT'
        xh = (W - hf.getlength(a1 + a2)) / 2
        d.text((xh, 90), a1, font=hf, fill=WHITE); d.text((xh + hf.getlength(a1), 90), a2, font=hf, fill=ORANGE)
        tw = fl.getlength(league.upper())
        d.rounded_rectangle(((W - tw) / 2 - 28, 160, (W + tw) / 2 + 28, 222), 31, fill=ORANGE)
        d.text(((W - tw) / 2, 170), league.upper(), font=fl, fill=WHITE)

        # HOOK (0 - 1.6s): big centered text with punch-in, then shrinks away
        if t < 1.8:
            a = _ease(t / 0.25) * (1 - _ease((t - 1.4) / 0.4))
            if a > 0:
                p = 1.25 - 0.25 * _ease(t / 0.3)
                f = ImageFont.truetype(FB, max(20, int(fhook.size * p)))
                d.rounded_rectangle((40, 820, W - 40, 1100), 40, fill=(6, 12, 24, int(225 * a)), outline=GOLD + (int(255 * a),), width=6)
                ctext(d, 960 - f.size * 0.62, hook.upper(), f, GOLD + (int(255 * a),))
            return im.convert('RGB')

        # away team slides from left
        a = _ease((t - 1.6) / 0.6)
        cx = int(W // 2 - (1 - a) * 700)
        disc(im, la, cx, 500, a, ca)
        d = ImageDraw.Draw(im, 'RGBA')
        if a > 0:
            ctext(d, 722, away['name'].upper(), fa, WHITE + (int(255 * a),))
            if sa: ctext(d, 722 + fa.size + 8, sa, fsub, GOLD + (int(255 * a),))
        # home team slides from right
        a = _ease((t - 2.0) / 0.6)
        cx = int(W // 2 + (1 - a) * 700)
        disc(im, lh, cx, 1215, a, ch)
        d = ImageDraw.Draw(im, 'RGBA')
        if a > 0:
            ctext(d, 1437, home['name'].upper(), fh, WHITE + (int(255 * a),))
            if sh: ctext(d, 1437 + fh.size + 8, sh, fsub, GOLD + (int(255 * a),))
        # VS with flash
        a = _ease((t - 2.5) / 0.3)
        if a > 0:
            p = 1 + 0.07 * math.sin(t * 6)
            r = int(78 * p * a)
            if t < 2.9:
                fl_ = Image.new('RGBA', (W, H), (255, 255, 255, int(120 * (1 - (t - 2.5) / 0.4))))
                im.alpha_composite(fl_); d = ImageDraw.Draw(im, 'RGBA')
            d.ellipse((W // 2 - r, 962 - r, W // 2 + r, 962 + r), fill=(6, 12, 24, 250), outline=GOLD, width=6)
            vf = ImageFont.truetype(FB, int(58 * p * a) + 1)
            d.text((W / 2 - vf.getlength('VS') / 2, 962 - vf.size * 0.62), 'VS', font=vf, fill=GOLD)
        # TV line under league pill
        a = _ease((t - 3.0) / 0.5)
        if a > 0:
            ctext(d, 250, tvline, ftv, WHITE + (int(240 * a),))
        # bottom: info panel (3.2-7.4s) then question + CTA
        y = 1610
        T1 = 10.5
        if t < T1:
            a = _ease((t - 3.2) / 0.5) * (1 - _ease((t - (T1 - 0.5)) / 0.5))
            if a > 0:
                d.rounded_rectangle((50, y, W - 50, H - 60), 36, fill=(6, 12, 24, int(235 * a)), outline=ORANGE + (int(255 * a),), width=4)
                ctext(d, y + 26, dayline, fday, GOLD + (int(255 * a),))
                ctext(d, y + 34 + fday.size + 8, timeline, ftime, WHITE + (int(255 * a),))
            if players:
                im = scene(im, t)
                d = ImageDraw.Draw(im, 'RGBA')
        else:
            a = _ease((t - 10.5) / 0.5)
            p = 1 + 0.025 * math.sin((t - 10.5) * 7)
            bx0, bx1 = int(50 + (1 - p) * 300), int(W - 50 - (1 - p) * 300)
            d.rounded_rectangle((bx0, y, bx1, H - 50), 36, fill=GOLD + (int(250 * a),))
            l0, l1, l2 = 'WHO WINS? Comment your pick', 'Live score + where to watch', 'Link in the comments \u2193'
            f0 = _fit(l0, FB, W - 180, 46, 28); f1 = _fit(l1, FR, W - 180, 44, 28); f2 = _fit(l2, FB, W - 180, 58, 34)
            ctext(d, y + 22, l0, f0, (180, 40, 10) + (int(255 * a),))
            d.line([(140, y + 34 + f0.size), (W - 140, y + 34 + f0.size)], fill=NAVY + (int(90 * a),), width=3)
            ctext(d, y + 50 + f0.size, l1, f1, NAVY + (int(255 * a),))
            ctext(d, y + 62 + f0.size + f1.size, l2, f2, NAVY + (int(255 * a),))
        return im.convert('RGB')

    if preview:
        return [frame(x) for x in preview]
    ff = shutil.which('ffmpeg')
    if not ff:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    wav = out + '.wav'
    _beat(wav)
    cmd = [ff, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS),
           '-i', '-', '-i', wav, '-shortest',
           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'veryfast', '-crf', '24',
           '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(int(DUR * FPS)):
        p.stdin.write(frame(i / FPS).tobytes())
    p.stdin.close()
    p.wait()
    try: os.remove(wav)
    except Exception: pass
    return out


