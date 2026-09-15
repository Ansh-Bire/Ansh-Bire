"""Pull live GitHub stats via GraphQL and render them as SVGs.

Runs unattended in the nightly Action, so it uses only the Python
standard library -- nothing to break in CI, no `pip install` step needed.
Font subsets are pre-built (scripts/fonts/*.woff2, made with pyftsubset)
and just read from disk here.

Two determinism traps this avoids:
  1. Pin the contribution window to whole UTC days. Left alone,
     contributionsCollection measures "the past year" from the moment of
     the request, so two runs minutes apart bucket days into different
     weeks and the sparkline looks like it changed every night for no
     reason.
  2. Filter repositories to privacy: PUBLIC. The workflow's token
     shouldn't (and can't) see private repos, but being explicit keeps
     the language percentages the same no matter who/what ran this.

Env vars (set by the workflow):
    GITHUB_TOKEN  -- the built-in Actions token; no PAT needed
    GH_LOGIN      -- github.repository_owner
"""
import base64
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path

API_URL = "https://api.github.com/graphql"
FONTS_DIR = Path(__file__).parent / "fonts"
OUT_DIR = Path(__file__).parent.parent

RAMP = " .`:-=+*cs#%@"  # the portrait's own ramp, quiet -> loud

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { date contributionCount }
        }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      nodes {
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def utc_window() -> tuple[str, str]:
    today = dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(days=364)
    frm = dt.datetime.combine(start, dt.time(0, 0, 0), dt.timezone.utc)
    to = dt.datetime.combine(today, dt.time(23, 59, 59), dt.timezone.utc)
    return frm.isoformat().replace("+00:00", "Z"), to.isoformat().replace("+00:00", "Z")


def fetch(login: str, token: str) -> dict:
    frm, to = utc_window()
    body = json.dumps({"query": QUERY, "variables": {"login": login, "from": frm, "to": to}}).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"{login}-profile-stats",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]["user"]


def b64_font(name: str) -> str:
    return base64.b64encode((FONTS_DIR / name).read_bytes()).decode("ascii")


def svg_shell(width: int, height: int, font_css: str, body: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
<defs><style>
{font_css}
text {{ fill: #15181c; }}
.dim {{ fill: #5b6068; }}
@media (prefers-color-scheme: dark) {{
  text {{ fill: #e8e6e1; }}
  .dim {{ fill: #9aa0a8; }}
}}
</style></defs>
{body}
</svg>
"""


def stats_font_css() -> str:
    return f"""@font-face {{ font-family: "StatsMono"; src: url(data:font/woff2;base64,{b64_font('stats-regular.woff2')}) format("woff2"); font-weight: 400; }}
@font-face {{ font-family: "StatsMono"; src: url(data:font/woff2;base64,{b64_font('stats-bold.woff2')}) format("woff2"); font-weight: 700; }}
text {{ font-family: "StatsMono", monospace; }}"""


# ---------------------------------------------------------------- stats.svg

def build_stats_svg(calendar: dict) -> str:
    total = calendar["totalContributions"]
    weeks = calendar["weeks"]
    weekly_totals = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in weeks]

    width, height = 460, 120
    pad_l, pad_r, pad_t, pad_b = 12, 12, 34, 18
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    hi = max(weekly_totals) or 1

    n = len(weekly_totals)
    step = plot_w / max(n - 1, 1)
    points = [
        (pad_l + i * step, pad_t + plot_h - (v / hi) * plot_h)
        for i, v in enumerate(weekly_totals)
    ]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area_pts = f"{pad_l:.1f},{pad_t + plot_h:.1f} " + polyline + f" {pad_l + (n - 1) * step:.1f},{pad_t + plot_h:.1f}"

    body = f"""<text x="12" y="24" font-size="20" font-weight="700">{total:,} contributions</text>
<text x="12" y="{height - 4}" font-size="10" class="dim">last 52 weeks, by week</text>
<polygon points="{area_pts}" fill="#4c8bf5" fill-opacity="0.15" stroke="none"/>
<polyline points="{polyline}" fill="none" stroke="#4c8bf5" stroke-width="1.5"/>"""
    return svg_shell(width, height, stats_font_css(), body)


# --------------------------------------------------------------- streak.svg

def compute_streaks(days: list[dict]) -> tuple[tuple[int, str, str], tuple[int, str, str]]:
    """Returns ((current_len, current_start, current_end), (longest_len, longest_start, longest_end))."""
    by_date = {dt.date.fromisoformat(d["date"]): d["contributionCount"] for d in days}
    ordered = sorted(by_date)

    longest_len, longest_start, longest_end = 0, None, None
    run_start = None
    run_len = 0
    for day in ordered:
        if by_date[day] > 0:
            if run_len == 0:
                run_start = day
            run_len += 1
            if run_len > longest_len:
                longest_len, longest_start, longest_end = run_len, run_start, day
        else:
            run_len = 0

    today = dt.datetime.now(dt.timezone.utc).date()
    cursor = today if by_date.get(today, 0) > 0 else today - dt.timedelta(days=1)
    current_len = 0
    current_end = cursor
    while by_date.get(cursor, 0) > 0:
        if current_len == 0:
            current_end = cursor
        current_len += 1
        current_start = cursor
        cursor -= dt.timedelta(days=1)
    if current_len == 0:
        current_start = current_end = today

    fmt = lambda d: f"{d.strftime('%b')} {d.day}" if d else "--"
    return (
        (current_len, fmt(current_start), fmt(current_end)),
        (longest_len, fmt(longest_start), fmt(longest_end)),
    )


def build_streak_svg(days: list[dict]) -> str:
    (cur_len, cur_from, cur_to), (long_len, long_from, long_to) = compute_streaks(days)
    width, height = 460, 60
    body = f"""<text x="12" y="24" font-size="13" font-weight="700">current streak: {cur_len} days</text>
<text x="12" y="40" font-size="10" class="dim">{cur_from} - {cur_to}</text>
<text x="240" y="24" font-size="13" font-weight="700">longest streak: {long_len} days</text>
<text x="240" y="40" font-size="10" class="dim">{long_from} - {long_to}</text>"""
    return svg_shell(width, height, stats_font_css(), body)


# ---------------------------------------------------------------- langs.svg

def build_langs_svg(repos: list[dict]) -> str:
    by_bytes: dict[str, int] = {}
    by_repo: dict[str, int] = {}
    colors: dict[str, str] = {}
    for repo in repos:
        seen_in_repo = set()
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            by_bytes[name] = by_bytes.get(name, 0) + edge["size"]
            colors[name] = edge["node"]["color"] or "#888"
            seen_in_repo.add(name)
        for name in seen_in_repo:
            by_repo[name] = by_repo.get(name, 0) + 1

    ranked = sorted(by_bytes.items(), key=lambda kv: kv[1], reverse=True)[:6]
    grand_total = sum(by_bytes.values()) or 1

    width = 460
    row_h = 20
    height = row_h * len(ranked) + 16
    max_bar = width - 250

    rows = []
    for i, (name, size) in enumerate(ranked):
        pct = 100 * size / grand_total
        bar_w = round(max_bar * pct / 100)
        y = 16 + i * row_h
        repo_count = by_repo.get(name, 0)
        rows.append(
            f'<text x="0" y="{y}" font-size="12">{name}</text>'
            f'<rect x="120" y="{y - 10}" width="{bar_w}" height="11" fill="{colors[name]}"/>'
            f'<text x="{120 + max_bar + 8}" y="{y}" font-size="11">{pct:.1f}%</text>'
            f'<text x="{width - 34}" y="{y}" font-size="11" class="dim">{repo_count}repo{"s" if repo_count != 1 else ""}</text>'
        )
    body = "\n".join(rows)
    return svg_shell(width, height, stats_font_css(), body)


# ----------------------------------------------------------------- year.svg

def build_year_svg(days: list[dict]) -> str:
    ordered = [d for d in days]
    counts = [d["contributionCount"] for d in ordered]
    nonzero = [c for c in counts if c > 0]
    hi = max(nonzero) if nonzero else 1
    ramp_len = len(RAMP)

    def ramp_char(c: int) -> str:
        if c == 0:
            return RAMP[0]
        idx = min(int(c / hi * (ramp_len - 1)) + 1, ramp_len - 1)
        return RAMP[idx]

    line = "".join(ramp_char(c) for c in counts)
    char_w = 6
    width = min(len(line), 371) * char_w + 20
    height = 30
    font_css = f"""@font-face {{ font-family: "RampMono"; src: url(data:font/woff2;base64,{b64_font('ramp.woff2')}) format("woff2"); }}
text {{ font-family: "RampMono", monospace; }}"""
    body = f'<text x="10" y="20" font-size="12" xml:space="preserve">{line}</text>'
    return svg_shell(width, height, font_css, body)


def main() -> None:
    login = os.environ["GH_LOGIN"]
    token = os.environ["GITHUB_TOKEN"]

    data = fetch(login, token)
    calendar = data["contributionsCollection"]["contributionCalendar"]
    days = [d for w in calendar["weeks"] for d in w["contributionDays"]]
    repos = data["repositories"]["nodes"]

    (OUT_DIR / "stats.svg").write_text(build_stats_svg(calendar), encoding="utf-8")
    (OUT_DIR / "streak.svg").write_text(build_streak_svg(days), encoding="utf-8")
    (OUT_DIR / "langs.svg").write_text(build_langs_svg(repos), encoding="utf-8")
    (OUT_DIR / "year.svg").write_text(build_year_svg(days), encoding="utf-8")
    print("wrote stats.svg, streak.svg, langs.svg, year.svg")


if __name__ == "__main__":
    main()
