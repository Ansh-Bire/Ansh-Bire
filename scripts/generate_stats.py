"""Pull live GitHub stats via GraphQL and render them as SVGs.

Requires a token with repo read access in the GH_TOKEN env var.
Writes: streak.svg, langs.svg, year.svg

Usage:
    GH_TOKEN=xxx python generate_stats.py <github-username>
"""
import base64
import datetime as dt
import io
import os
import sys
from pathlib import Path

import requests
from fontTools import subset
from fontTools.ttLib import TTFont

FONT_PATH = Path(__file__).parent / "fonts" / "JetBrainsMono-Regular.ttf"
API_URL = "https://api.github.com/graphql"
YEAR_RAMP = " :+#@"  # quiet -> loud, matches the portrait's ramp

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      nodes {
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node { name color }
          }
        }
      }
    }
  }
}
"""


def fetch(login: str, token: str) -> dict:
    resp = requests.post(
        API_URL,
        json={"query": QUERY, "variables": {"login": login}},
        headers={"Authorization": f"bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]["user"]


def subset_font_bytes(characters: str) -> bytes:
    font = TTFont(str(FONT_PATH))
    options = subset.Options()
    options.flavor = "woff2"
    options.desubroutinize = True
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=characters)
    subsetter.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def font_face_css(font_family: str, characters: str) -> str:
    b64 = base64.b64encode(subset_font_bytes(characters)).decode("ascii")
    return f"""@font-face {{
  font-family: "{font_family}";
  src: url(data:font/woff2;base64,{b64}) format("woff2");
}}"""


def svg_wrap(width: int, height: int, font_css: str, body: str, font_family: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
<defs><style>
{font_css}
text {{ font-family: "{font_family}", monospace; fill: currentColor; }}
</style></defs>
{body}
</svg>
"""


def compute_streaks(days: list[dict]) -> tuple[int, int]:
    current = longest = run = 0
    today = dt.date.today()
    for day in days:
        if day["contributionCount"] > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    # current streak: walk backwards from today (or yesterday if today is empty)
    by_date = {dt.date.fromisoformat(d["date"]): d["contributionCount"] for d in days}
    cursor = today
    if by_date.get(cursor, 0) == 0:
        cursor -= dt.timedelta(days=1)
    while by_date.get(cursor, 0) > 0:
        current += 1
        cursor -= dt.timedelta(days=1)
    return current, longest


def build_streak_svg(days: list[dict]) -> str:
    current, longest = compute_streaks(days)
    text = f"current streak: {current} days   ·   longest streak: {longest} days"
    font_css = font_face_css("StatsMono", text)
    width = len(text) * 8 + 20
    height = 36
    body = f'<text x="10" y="24" font-size="14">{text}</text>'
    return svg_wrap(width, height, font_css, body, "StatsMono")


def build_langs_svg(repos: list[dict]) -> str:
    totals: dict[str, tuple[int, str]] = {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            size = edge["size"]
            color = edge["node"]["color"] or "#888"
            prev = totals.get(name, (0, color))
            totals[name] = (prev[0] + size, color)

    ranked = sorted(totals.items(), key=lambda kv: kv[1][0], reverse=True)[:6]
    grand_total = sum(v[0] for v in totals.values()) or 1

    lines = []
    for name, (size, color) in ranked:
        pct = 100 * size / grand_total
        lines.append(f"{name} {pct:.1f}%")
    text_all = " | ".join(lines)
    font_css = font_face_css("StatsMono", text_all + "0123456789.%")

    width = 620
    row_h = 22
    height = row_h * len(ranked) + 16
    rows = []
    max_bar = width - 220
    for i, (name, (size, color)) in enumerate(ranked):
        pct = 100 * size / grand_total
        bar_w = round(max_bar * pct / 100)
        y = 16 + i * row_h
        rows.append(
            f'<text x="0" y="{y}" font-size="13">{name:<14}</text>'
            f'<rect x="150" y="{y - 11}" width="{bar_w}" height="12" fill="{color}"/>'
            f'<text x="{150 + max_bar + 8}" y="{y}" font-size="13">{pct:.1f}%</text>'
        )
    body = "\n".join(rows)
    return svg_wrap(width, height, font_css, body, "StatsMono")


def build_year_svg(days: list[dict]) -> str:
    counts = [d["contributionCount"] for d in days]
    nonzero = [c for c in counts if c > 0]
    hi = max(nonzero) if nonzero else 1

    def ramp_char(c: int) -> str:
        if c == 0:
            return YEAR_RAMP[0]
        idx = min(int(c / hi * (len(YEAR_RAMP) - 1)) + 1, len(YEAR_RAMP) - 1)
        return YEAR_RAMP[idx]

    line = "".join(ramp_char(c) for c in counts)
    font_css = font_face_css("StatsMono", line + " ")
    width = min(len(line), 371) * 6 + 20
    height = 30
    body = f'<text x="10" y="20" font-size="12" xml:space="preserve">{line}</text>'
    return svg_wrap(width, height, font_css, body, "StatsMono")


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: generate_stats.py <github-username>", file=sys.stderr)
        raise SystemExit(1)
    login = sys.argv[1]
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("GH_TOKEN env var is required", file=sys.stderr)
        raise SystemExit(1)

    data = fetch(login, token)
    weeks = data["contributionsCollection"]["contributionCalendar"]["weeks"]
    days = [d for w in weeks for d in w["contributionDays"]]
    repos = data["repositories"]["nodes"]

    out_dir = Path(__file__).parent.parent
    (out_dir / "streak.svg").write_text(build_streak_svg(days), encoding="utf-8")
    (out_dir / "langs.svg").write_text(build_langs_svg(repos), encoding="utf-8")
    (out_dir / "year.svg").write_text(build_year_svg(days), encoding="utf-8")
    print("wrote streak.svg, langs.svg, year.svg")


if __name__ == "__main__":
    main()
