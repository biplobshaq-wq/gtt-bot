#!/usr/bin/env python3
"""One high-interest football match guide per day for Game Time Tonight.

This deliberately replaces the old high-volume sports queue. It publishes at most one
original, fact-checked article per America/New_York calendar day, focused on UEFA and
major European leagues for a US reader. It does NOT embed match broadcasts, download
video, copy news stories, or use club/player photos or logos. The only embedded dynamic
item is the blog theme's existing score widget, fed with public schedule/score data.

Run in GitHub Actions with WEBAPP and WEB_SECRET set. Use --dry-run to inspect the
next candidate without writing to Blogger.
"""
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

WEBAPP = os.environ.get("WEBAPP", "").strip()
SECRET = os.environ.get("WEB_SECRET", "").strip()
BLOG_ID = "8757754119349417883"
REPO_RAW = "https://raw.githubusercontent.com/biplobshaq-wq/gtt-bot/main/"
STATE_PATH = Path("state.json")
ET = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
UA = {"User-Agent": "Mozilla/5.0 (compatible; GameTimeTonight editorial scheduler/1.0)"}
ESPN = "https://site.api.espn.com/apis/site/v2/sports/"

# European football first; the weighting chooses genuinely high-interest fixtures, not
# a large volume of low-interest games. Football data comes from a public schedule API
# and every sentence supplied to the writer must be grounded in the facts gathered here.
LEAGUES = (
    ("soccer/uefa.champions", "UEFA Champions League", 500),
    ("soccer/uefa.europa", "UEFA Europa League", 410),
    # A top-level international window is the Tier-1 fallback when domestic clubs are idle.
    ("soccer/uefa.nations", "UEFA Nations League", 380),
    ("soccer/eng.1", "English Premier League", 330),
    ("soccer/esp.1", "Spanish LaLiga", 285),
    ("soccer/ger.1", "German Bundesliga", 275),
    ("soccer/ita.1", "Italian Serie A", 275),
    ("soccer/fra.1", "French Ligue 1", 235),
)

# This is editorial prioritisation, not a claim about quality or betting odds. A fixture
# with two widely followed clubs is prioritised over an otherwise identical fixture.
CLUB_BOOST = {
    "Arsenal": 48, "Chelsea": 42, "Liverpool": 50, "Manchester City": 50,
    "Manchester United": 48, "Tottenham Hotspur": 35, "Newcastle United": 24,
    "Real Madrid": 52, "Barcelona": 52, "Atlético Madrid": 38,
    "Bayern Munich": 48, "Borussia Dortmund": 38, "Bayer Leverkusen": 31,
    "Paris Saint-Germain": 46, "Inter Milan": 40, "AC Milan": 39,
    "Juventus": 40, "Napoli": 30, "Roma": 25,
    # International sides used only when a UEFA Nations League fixture is selected.
    "England": 50, "France": 50, "Spain": 50, "Germany": 48,
    "Portugal": 46, "Italy": 46, "Netherlands": 40, "Belgium": 36,
    "Croatia": 32, "Denmark": 28, "Norway": 25, "Austria": 24,
}


def get_json(url, timeout=35):
    err = None
    for _ in range(3):
        try:
            request = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # network/API failures must never cause a guessed post
            err = exc
            time.sleep(2)
    raise RuntimeError(str(err))


def api_post(payload, timeout=240):
    if not WEBAPP or not SECRET:
        raise RuntimeError("WEBAPP or WEB_SECRET is missing")
    request_body = dict(payload, secret=SECRET, blogId=BLOG_ID)
    request = urllib.request.Request(
        WEBAPP,
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError("Blogger web app: " + str(data.get("error", "unknown error"))[:300])
    return data


def now_utc():
    return dt.datetime.now(UTC)


def load_state():
    try:
        state = json.loads(STATE_PATH.read_text())
    except Exception:
        state = {}
    state.setdefault("games", {})
    state.setdefault("euro_daily", {})
    return state


def save_state(state):
    games = state.get("games", {})
    # Keep enough history to prevent duplicate game pages but do not grow forever.
    if len(games) > 500:
        old = sorted(games, key=lambda gid: games[gid].get("date", ""))[:len(games) - 500]
        for game_id in old:
            del games[game_id]
    STATE_PATH.write_text(json.dumps(state, indent=1, ensure_ascii=False) + "\n")


def event_time(event):
    return dt.datetime.fromisoformat(event["date"].replace("Z", "+00:00"))


def broadcast_names(competition):
    names = []
    for broadcast in competition.get("broadcasts") or []:
        for name in broadcast.get("names") or []:
            if name not in names:
                names.append(name)
    return names


def team_name(competitor):
    team = competitor.get("team") or {}
    return team.get("displayName") or team.get("shortDisplayName") or team.get("name") or "Team"


def competition_teams(competition):
    sides = {x.get("homeAway"): x for x in competition.get("competitors") or []}
    if "away" not in sides or "home" not in sides:
        return None, None
    return team_name(sides["away"]), team_name(sides["home"])


def club_interest(name):
    # ESPN sometimes includes a city prefix or a club naming variation; exact matches are
    # strongest but substring matching keeps the schedule source usable across leagues.
    return max((score for club, score in CLUB_BOOST.items() if club.lower() in name.lower()), default=0)


def fixture_score(league_weight, away, home, hours_until):
    clubs = club_interest(away) + club_interest(home)
    duel_bonus = 35 if club_interest(away) and club_interest(home) else 0
    # A match in the next day is preferable, but never displaces a major European tie
    # simply because it is closer.
    timing = max(0, 32 - int(max(hours_until, 0)))
    return league_weight + clubs + duel_bonus + timing


def candidates(now):
    selected = {}
    et_today = now.astimezone(ET).date()
    # Four days allows a daily post during a sparse midweek without inventing news.
    for api_league, label, weight in LEAGUES:
        for offset in range(5):
            day = et_today + dt.timedelta(days=offset)
            url = f"{ESPN}{api_league}/scoreboard?dates={day:%Y%m%d}&limit=500"
            try:
                payload = get_json(url)
            except Exception as exc:
                print("schedule unavailable", api_league, exc)
                continue
            for event in payload.get("events") or []:
                competition = (event.get("competitions") or [{}])[0]
                status = ((competition.get("status") or {}).get("type") or {}).get("state")
                if status != "pre":
                    continue
                try:
                    kickoff = event_time(event)
                except Exception:
                    continue
                hours = (kickoff - now).total_seconds() / 3600
                if not 3 <= hours <= 96:
                    continue
                away, home = competition_teams(competition)
                if not away or not home:
                    continue
                event_id = str(event.get("id") or "")
                if not event_id:
                    continue
                selected[event_id] = {
                    "id": event_id,
                    "api_league": api_league,
                    "league": label,
                    "weight": weight,
                    "kickoff": kickoff,
                    "away": away,
                    "home": home,
                    "tv": broadcast_names(competition),
                    "score": fixture_score(weight, away, home, hours),
                }
    return list(selected.values())


def pull_match_facts(game):
    """Gather only schedule/score facts. Missing data remains missing; it is never filled in."""
    payload = get_json(f"{ESPN}{game['api_league']}/summary?event={game['id']}")
    competition = ((payload.get("header") or {}).get("competitions") or [{}])[0]
    sides = {x.get("homeAway"): x for x in competition.get("competitors") or []}
    venue = (payload.get("gameInfo") or {}).get("venue") or {}
    address = venue.get("address") or {}

    def record(side):
        records = side.get("record") or []
        return (records[0].get("summary") if records else "") or ""

    kickoff = game["kickoff"]
    facts = {
        "league": game["league"],
        "away_team": team_name(sides.get("away") or {}),
        "home_team": team_name(sides.get("home") or {}),
        "kickoff_et": kickoff.astimezone(ET).strftime("%A, %B %-d, %Y at %-I:%M %p ET").replace(":00 ", " "),
        "kickoff_ct": kickoff.astimezone(ZoneInfo("America/Chicago")).strftime("%-I:%M %p CT").replace(":00 ", " "),
        "kickoff_pt": kickoff.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%-I:%M %p PT").replace(":00 ", " "),
        "venue": venue.get("fullName") or "",
        "city": ", ".join(x for x in (address.get("city"), address.get("state") or address.get("country")) if x),
        "away_record": record(sides.get("away") or {}),
        "home_record": record(sides.get("home") or {}),
        "us_broadcasts": broadcast_names(competition),
        "source_note": "Times and listed coverage are schedule data and can change.",
    }
    return facts


def title_for(facts):
    return f"{facts['away_team']} vs {facts['home_team']}: US Time & TV"


def prompt_for(facts):
    # The Apps Script call returns an LLM result, but the hard prompt allows no unprovided
    # claims and its output is escaped before Blogger receives it.
    return f"""You are the editorial writer for Game Time Tonight, a US sports-information blog.
Write a fresh, concise match guide in original American English. It must help a US reader
find the kickoff time, listed coverage, venue and live-score information for one upcoming
European football match. Do not copy or closely paraphrase any article, preview, headline,
commentary or broadcaster text. Do not add facts that are absent from the JSON.

Hard rules:
- Use only the supplied JSON facts. Do not invent injuries, form, tactics, transfers, odds,
  standings, quotes, rivalries, players, records, streaming services or a result.
- Never tell readers where to watch a pirated stream or imply that this site streams video.
- Mention that schedules and coverage can change and readers should check their local listing.
- Write 260–420 words total, plain 8th-grade US English. No Markdown, no HTML, no filler.
- If broadcast information is empty, say only "US coverage was not listed in the schedule data"
  and tell readers to check the competition's official listings.
- Do not use phrases such as "ultimate guide", "delve", "in today's world" or "as an AI".

FACTS (JSON):
{json.dumps(facts, ensure_ascii=False)}

Return JSON only in this exact structure:
{{
  "lead": "two factual sentences",
  "details": ["short factual paragraph", "short factual paragraph"],
  "watch_note": "one factual sentence about following the score",
  "meta": "120-155 character factual search description"
}}"""


def clean_ai(raw):
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.I).strip()
    data = json.loads(text)
    lead = str(data.get("lead") or "").strip()
    details = [str(x).strip() for x in (data.get("details") or []) if str(x).strip()][:3]
    watch_note = str(data.get("watch_note") or "").strip()
    meta = str(data.get("meta") or "").strip()[:155]
    if not lead or len(details) < 1 or not watch_note:
        raise ValueError("writer response lacks required factual sections")
    # Treat generated prose as text, never HTML, so the writer cannot inject embeds/links.
    return {"lead": lead, "details": details, "watch_note": watch_note, "meta": meta}


def font(size, bold=False):
    options = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in options:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def wrapped(draw, text, font_obj, max_width):
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = (current + " " + word).strip()
        if current and draw.textbbox((0, 0), candidate, font=font_obj)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def make_original_graphic(facts, game_id):
    """A text-only original graphic: no team badge, player photo, broadcast footage or logo."""
    image = Image.new("RGB", (1200, 675), "#081b33")
    draw = ImageDraw.Draw(image)
    # A simple original pitch-inspired background, not a copied broadcast or club creative.
    draw.rectangle((0, 0, 1200, 675), fill="#081b33")
    draw.ellipse((-150, 70, 1350, 900), outline="#1f5e61", width=6)
    draw.line((600, 0, 600, 675), fill="#1f5e61", width=5)
    draw.ellipse((510, 247, 690, 427), outline="#1f5e61", width=5)
    draw.rectangle((42, 42, 1158, 633), outline="#65d3c8", width=3)

    small, large, mid = font(28, True), font(58, True), font(36, True)
    draw.text((74, 72), facts["league"].upper(), fill="#65d3c8", font=small)
    draw.text((74, 122), "MATCH GUIDE", fill="white", font=large)
    y = 260
    for line in wrapped(draw, facts["away_team"], mid, 460):
        draw.text((78, y), line, fill="white", font=mid)
        y += 46
    draw.text((565, 290), "VS", fill="#ffca6a", font=font(48, True))
    y = 260
    for line in wrapped(draw, facts["home_team"], mid, 460):
        draw.text((690, y), line, fill="white", font=mid)
        y += 46
    draw.rounded_rectangle((74, 525, 1126, 600), radius=16, fill="#123952")
    date = facts["kickoff_et"].replace(", 2026", "")
    draw.text((105, 546), date, fill="white", font=font(27, True))
    draw.text((75, 618), "Original Game Time Tonight graphic — schedule information only", fill="#a9c5d4", font=font(18))
    path = Path("img") / f"euro-{game_id}.jpg"
    path.parent.mkdir(exist_ok=True)
    image.save(path, "JPEG", quality=90, optimize=True)
    return str(path)


def html_article(game, facts, draft, image_url):
    coverage = ", ".join(facts["us_broadcasts"]) if facts["us_broadcasts"] else "US coverage was not listed in the schedule data"
    venue = facts["venue"] + (", " + facts["city"] if facts["city"] else "")
    rows = [
        ("Match", f"{facts['away_team']} at {facts['home_team']}"),
        ("Competition", facts["league"]),
        ("US time", f"{facts['kickoff_et']} ({facts['kickoff_ct']} / {facts['kickoff_pt']})"),
        ("Listed US coverage", coverage),
        ("Venue", venue or "TBA"),
    ]
    records = []
    if facts["away_record"]:
        records.append(f"{facts['away_team']}: {facts['away_record']}")
    if facts["home_record"]:
        records.append(f"{facts['home_team']}: {facts['home_record']}")
    if records:
        rows.append(("Schedule record", " · ".join(records)))
    table = "".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>" for label, value in rows
    )
    detail_html = "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in draft["details"])
    return f"""<img alt="{html.escape(facts['away_team'])} vs {html.escape(facts['home_team'])} US kickoff time and match guide" src="{image_url}" width="1200" height="675"/>
<p>{html.escape(draft['lead'])}</p>
<div class="gtt-live" data-league="{html.escape(game['api_league'])}" data-event="{html.escape(game['id'])}"><div class="st">Loading live score…</div></div>
<h2>{html.escape(facts['away_team'])} vs {html.escape(facts['home_team'])}: match details</h2>
<table>{table}</table>
<h2>What to know before kickoff</h2>
{detail_html}
<h2>Live score and updates</h2>
<p>{html.escape(draft['watch_note'])}</p>
<p>Game Time Tonight does not stream matches or host match video. Times and listed coverage come from public schedule data and can change, so check the competition's official local listing before kickoff.</p>"""


def save_image_to_repo(path):
    subprocess.run(["git", "add", path], check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    subprocess.run(["git", "commit", "-q", "-m", "original european football graphic"], check=True)
    subprocess.run(["git", "pull", "-q", "--rebase"], check=False)
    subprocess.run(["git", "push", "-q"], check=True)


def update_finished_matches(state, now):
    """Update only existing original articles with a verified final score; never create a result post."""
    updated = 0
    for game_id, item in list(state["games"].items()):
        if item.get("format") != "euro_daily" or item.get("final") or updated >= 2:
            continue
        try:
            kickoff = dt.datetime.fromisoformat(item["kickoff"])
        except Exception:
            continue
        if now < kickoff + dt.timedelta(hours=2):
            continue
        try:
            summary = get_json(f"{ESPN}{item['api_league']}/summary?event={game_id}")
            competition = ((summary.get("header") or {}).get("competitions") or [{}])[0]
            if (((competition.get("status") or {}).get("type") or {}).get("state")) != "post":
                continue
            teams = {x.get("homeAway"): x for x in competition.get("competitors") or []}
            away, home = teams.get("away") or {}, teams.get("home") or {}
            score = f"{team_name(away)} {away.get('score', '')}–{home.get('score', '')} {team_name(home)}"
            feed = get_json(f"https://www.blogger.com/feeds/{BLOG_ID}/posts/default/{item['post']}?alt=json")
            body = feed["entry"]["content"]["$t"]
            if "Verified final score:" in body:
                item["final"] = True
                continue
            final_box = f'<div style="background:#eef9f7;border-left:5px solid #137c72;padding:14px;margin:0 0 18px"><b>Verified final score:</b> {html.escape(score)}</div>'
            body = body.replace("</div></div>", "</div></div>" + final_box, 1) if "gtt-live" in body else final_box + body
            api_post({"action": "update", "postId": item["post"], "html": body, "labels": list(dict.fromkeys(item.get("labels", []) + ["Result"]))})
            item["final"] = True
            updated += 1
            print("final score updated", game_id, score)
        except Exception as exc:
            print("final score update skipped", game_id, str(exc)[:180])


def publish_one(state, now, dry_run=False):
    day = now.astimezone(ET).strftime("%Y-%m-%d")
    if state["euro_daily"].get(day):
        print("daily article already published for", day)
        return None
    unseen = [game for game in candidates(now) if game["id"] not in state["games"]]
    if not unseen:
        print("no suitable unpublished European fixture in the next 96 hours")
        return None
    game = max(unseen, key=lambda item: item["score"])
    facts = pull_match_facts(game)
    print("selected", facts["league"], facts["away_team"], "vs", facts["home_team"], facts["kickoff_et"], "score", game["score"])
    if dry_run:
        print(json.dumps({"game": game, "facts": facts}, indent=2, default=str))
        return game

    writer = api_post({"action": "gemini", "prompt": prompt_for(facts)})
    draft = clean_ai(writer.get("text", ""))
    image_path = make_original_graphic(facts, game["id"])
    # The image must exist on the public repository before Blogger stores the post URL.
    save_image_to_repo(image_path)
    post = api_post({
        "action": "post",
        "title": title_for(facts),
        "html": html_article(game, facts, draft, REPO_RAW + image_path),
        "labels": [facts["league"], "European Football", "Preview", facts["away_team"], facts["home_team"]],
    })
    state["games"][game["id"]] = {
        "format": "euro_daily",
        "post": post["id"],
        "url": post["url"],
        "date": day,
        "kickoff": game["kickoff"].isoformat(),
        "api_league": game["api_league"],
        "league": facts["league"],
        "title": title_for(facts),
        "labels": [facts["league"], "European Football", "Preview", facts["away_team"], facts["home_team"]],
        "final": False,
        "image": image_path,
    }
    state["euro_daily"][day] = game["id"]
    print("published", post["url"])
    return game


def main():
    dry_run = "--dry-run" in sys.argv
    now = now_utc()
    state = load_state()
    if not dry_run:
        update_finished_matches(state, now)
    publish_one(state, now, dry_run=dry_run)
    if not dry_run:
        save_state(state)


if __name__ == "__main__":
    main()
