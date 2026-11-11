#!/usr/bin/env python3
"""Generate the profile README stats cards from public GitHub data.

The cards replace github-readme-stats. No personal access token is required.
GitHub Actions passes the built-in GITHUB_TOKEN for rate limit headroom; public
endpoints are used either way, and private repository contents are never read.

Activity on the stats card is the last-year contribution total from GitHub's
contribution calendar (the same number shown on the public profile). If that
calendar cannot be read, the card falls back to public commits authored in the
last 365 days.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "profile-readme-stats"
API_ROOT = "https://api.github.com"
TOP_LANGUAGES = 8
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")

# Primer Octicons (MIT). Copyright (c) GitHub, Inc.
# https://github.com/primer/octicons
ICONS: dict[str, tuple[str, ...]] = {
    "star": (
        "M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Zm0 2.445L6.615 5.5a.75.75 0 0 1-.564.41l-3.097.45 2.24 2.184a.75.75 0 0 1 .216.664l-.528 3.084 2.769-1.456a.75.75 0 0 1 .698 0l2.77 1.456-.53-3.084a.75.75 0 0 1 .216-.664l2.24-2.183-3.096-.45a.75.75 0 0 1-.564-.41L8 2.694Z",
    ),
    "repo": (
        "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z",
    ),
    "people": (
        "M2 5.5a3.5 3.5 0 1 1 5.898 2.549 5.508 5.508 0 0 1 3.034 4.084.75.75 0 1 1-1.482.235 4 4 0 0 0-7.9 0 .75.75 0 0 1-1.482-.236A5.507 5.507 0 0 1 3.102 8.05 3.493 3.493 0 0 1 2 5.5ZM11 4a3.001 3.001 0 0 1 2.22 5.018 5.01 5.01 0 0 1 2.56 3.012.749.749 0 0 1-.885.954.752.752 0 0 1-.549-.514 3.507 3.507 0 0 0-2.522-2.372.75.75 0 0 1-.574-.73v-.352a.75.75 0 0 1 .416-.672A1.5 1.5 0 0 0 11 5.5.75.75 0 0 1 11 4Zm-5.5-.5a2 2 0 1 0-.001 3.999A2 2 0 0 0 5.5 3.5Z",
    ),
    "commit": (
        "M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5Zm-1.43-.75a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0Z",
    ),
    "pr": (
        "M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354ZM3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z",
    ),
    "issue": (
        "M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z",
        "M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Z",
    ),
}

# GitHub Linguist colors for languages that show up often. Unknown names get a
# stable color from FALLBACK_COLORS.
LANG_COLORS = {
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Python": "#3572A5",
    "Java": "#b07219",
    "PHP": "#4F5D95",
    "C": "#555555",
    "C++": "#f34b7d",
    "C#": "#178600",
    "Go": "#00ADD8",
    "Rust": "#dea584",
    "Ruby": "#701516",
    "Swift": "#F05138",
    "Kotlin": "#A97BFF",
    "Dart": "#00B4AB",
    "Scala": "#c22d40",
    "Shell": "#89e051",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "SCSS": "#c6538c",
    "Less": "#1d365d",
    "Vue": "#41b883",
    "Svelte": "#ff3e00",
    "Astro": "#ff5a03",
    "Jupyter Notebook": "#DA5B0B",
    "Markdown": "#083fa1",
    "MDX": "#fcb32c",
    "Hack": "#878787",
    "Haskell": "#5e5086",
    "Elixir": "#6e4a7e",
    "Erlang": "#B83998",
    "Clojure": "#db5855",
    "Lua": "#000080",
    "Perl": "#0298c3",
    "R": "#198CE7",
    "PowerShell": "#012456",
    "Dockerfile": "#384d54",
    "Makefile": "#427819",
    "HCL": "#844FBA",
    "GraphQL": "#e10098",
    "Solidity": "#AA6746",
    "Zig": "#ec915c",
    "Nix": "#7e7eff",
    "YAML": "#cb171e",
    "JSON": "#292929",
    "TOML": "#9c4221",
    "SQL": "#e38c00",
    "PLpgSQL": "#336790",
    "Batchfile": "#C1F12E",
    "Blade": "#f7523f",
    "Twig": "#c1d026",
    "Objective-C": "#438eff",
    "MATLAB": "#e16737",
    "Groovy": "#4298b8",
    "Julia": "#a270ba",
    "Elm": "#60B5CC",
    "F#": "#b845fc",
    "Visual Basic .NET": "#945db7",
    "Assembly": "#6E4C13",
    "CMake": "#DA3434",
    "Nginx": "#009639",
    "Procfile": "#3B2F63",
    "Bicep": "#519aba",
    "CoffeeScript": "#244776",
    "Sass": "#a53b70",
}
FALLBACK_COLORS = (
    "#0969da",
    "#8250df",
    "#bf3989",
    "#cf222e",
    "#bc4c00",
    "#1a7f37",
    "#0550ae",
    "#9a6700",
)

THEMES = {
    "light": {
        "text": "#24292f",
        "muted": "#57606a",
        "icon": "#4c71f2",
        "other": "#d0d7de",
        "dot_stroke": "#8c959f",
    },
    "dark": {
        "text": "#e6edf3",
        "muted": "#8b949e",
        "icon": "#58a6ff",
        "other": "#30363d",
        "dot_stroke": "#6e7681",
    },
}

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


class ApiError(RuntimeError):
    pass


def resolve_login() -> str:
    login = os.environ.get("STATS_LOGIN", "").strip()
    if not login:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if "/" in repo:
            login = repo.split("/", 1)[0]
    if not login:
        login = "Saladin2020"
    if not LOGIN_RE.fullmatch(login):
        raise SystemExit(f"invalid GitHub login: {login!r}")
    return login


def resolve_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    token = token.strip()
    return token or None


def _sleep_backoff(attempt: int, headers) -> None:
    retry_after = headers.get("Retry-After") if headers is not None else None
    if retry_after and str(retry_after).isdigit():
        delay = min(int(retry_after), 20)
    else:
        delay = min(2**attempt, 20)
    time.sleep(delay)


def request(url: str, *, token: str | None, method: str = "GET", body: dict | None = None, accept: str) -> tuple[int, str, object]:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if url.startswith(API_ROOT):
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        if token:
            headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    last_error: Exception | None = None
    for attempt in range(4):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = response.read().decode("utf-8")
                link = response.headers.get("Link")
                return response.status, payload, link
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            retryable = exc.code in (429, 500, 502, 503, 504) or (
                exc.code == 403 and "rate limit" in detail.lower()
            )
            if retryable and attempt < 3:
                _sleep_backoff(attempt, exc.headers)
                last_error = exc
                continue
            path = urllib.parse.urlparse(url).path
            raise ApiError(f"HTTP {exc.code} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            if attempt < 3:
                _sleep_backoff(attempt, None)
                last_error = exc
                continue
            raise ApiError(f"request failed for {urllib.parse.urlparse(url).path}: {exc.reason}") from exc
    raise ApiError(f"request failed: {last_error}")


def api_json(url: str, *, token: str | None, method: str = "GET", body: dict | None = None):
    _status, payload, link = request(
        url,
        token=token,
        method=method,
        body=body,
        accept="application/vnd.github+json",
    )
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ApiError(f"invalid JSON from {urllib.parse.urlparse(url).path}") from exc
    return parsed, link


def api_text(url: str) -> str:
    _status, payload, _link = request(url, token=None, accept="text/html")
    return payload


def next_url(link_header) -> str | None:
    if not link_header:
        return None
    for part in str(link_header).split(","):
        section, _, rel = part.partition(";")
        if 'rel="next"' in rel:
            url = section.strip()
            if url.startswith("<") and url.endswith(">"):
                return url[1:-1]
    return None


def paginate(url: str, token: str | None) -> list:
    items: list = []
    while url:
        payload, link = api_json(url, token=token)
        if isinstance(payload, dict):
            message = payload.get("message", "unexpected object response")
            raise ApiError(message)
        items.extend(payload)
        url = next_url(link)
    return items


def graphql_contributions(login: str, token: str) -> int:
    query = """
      query($login: String!) {
        user(login: $login) {
          contributionsCollection {
            contributionCalendar { totalContributions }
          }
        }
      }
    """
    payload, _link = api_json(
        f"{API_ROOT}/graphql",
        token=token,
        method="POST",
        body={"query": query, "variables": {"login": login}},
    )
    if payload.get("errors"):
        message = payload["errors"][0].get("message", "graphql error")
        raise ApiError(message)
    user = (payload.get("data") or {}).get("user")
    if not user:
        raise ApiError(f"user {login} not found")
    return int(user["contributionsCollection"]["contributionCalendar"]["totalContributions"])


def html_contributions(login: str) -> int:
    html = api_text(f"https://github.com/users/{urllib.parse.quote(login)}/contributions")
    day_counts = [int(value) for value in re.findall(r"(\d+) contributions? on ", html)]
    if day_counts:
        return sum(day_counts)
    match = re.search(r"([\d,]+)\s+contributions\s+in the last year", html)
    if not match:
        raise ApiError("contribution calendar was not in the profile response")
    return int(match.group(1).replace(",", ""))


def search_count(url: str, token: str | None) -> int:
    payload, _link = api_json(url, token=token)
    if "total_count" not in payload:
        raise ApiError(payload.get("message", "search failed"))
    return int(payload["total_count"])


def commits_last_year(login: str, token: str | None) -> int:
    from datetime import datetime, timedelta, timezone

    start = (datetime.now(timezone.utc) - timedelta(days=365)).date().isoformat()
    query = f"author:{login} author-date:>={start}"
    url = f"{API_ROOT}/search/commits?{urllib.parse.urlencode({'q': query, 'per_page': 1})}"
    return search_count(url, token)


def load_activity(login: str, token: str | None) -> tuple[int, str, str]:
    errors: list[str] = []
    if token:
        try:
            return graphql_contributions(login, token), "Contribs (1 year)", "graphql"
        except ApiError as exc:
            errors.append(f"graphql: {exc}")
    try:
        return html_contributions(login), "Contribs (1 year)", "profile"
    except ApiError as exc:
        errors.append(f"profile: {exc}")
    try:
        return commits_last_year(login, token), "Commits (1 year)", "commit-search"
    except ApiError as exc:
        errors.append(f"commits: {exc}")
    raise ApiError("could not load activity: " + "; ".join(errors))


def load_languages(repos: list, token: str | None) -> list[tuple[str, int]]:
    totals: dict[str, int] = {}
    for repo in repos:
        if repo.get("fork"):
            continue
        payload, _link = api_json(repo["languages_url"], token=token)
        if not isinstance(payload, dict):
            raise ApiError(f"{repo.get('full_name', 'repository')} languages response was not an object")
        if "message" in payload and not any(isinstance(value, int) for value in payload.values()):
            raise ApiError(f"{repo.get('full_name', 'repository')}: {payload.get('message')}")
        for name, bytes_count in payload.items():
            if isinstance(bytes_count, int):
                totals[name] = totals.get(name, 0) + bytes_count
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0].lower()))
    return ranked


def load_stats(login: str, token: str | None) -> dict:
    user, _link = api_json(f"{API_ROOT}/users/{urllib.parse.quote(login)}", token=token)
    if not isinstance(user, dict) or "public_repos" not in user:
        message = user.get("message", "user lookup failed") if isinstance(user, dict) else "user lookup failed"
        raise ApiError(message)

    repos = paginate(
        f"{API_ROOT}/users/{urllib.parse.quote(login)}/repos?per_page=100&type=owner",
        token,
    )
    stars = sum(int(repo.get("stargazers_count") or 0) for repo in repos if not repo.get("fork"))
    languages = load_languages(repos, token)
    activity, activity_label, activity_source = load_activity(login, token)

    pr_query = urllib.parse.urlencode(
        {"q": f"author:{login} type:pr is:public", "per_page": 1}
    )
    issue_query = urllib.parse.urlencode(
        {"q": f"author:{login} type:issue is:public", "per_page": 1}
    )
    pull_requests = search_count(f"{API_ROOT}/search/issues?{pr_query}", token)
    issues = search_count(f"{API_ROOT}/search/issues?{issue_query}", token)

    return {
        "login": login,
        "stars": stars,
        "public_repos": int(user["public_repos"]),
        "followers": int(user["followers"]),
        "activity": activity,
        "activity_label": activity_label,
        "activity_source": activity_source,
        "pull_requests": pull_requests,
        "issues": issues,
        "languages": languages,
    }


def svg_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def fmt_int(value: int) -> str:
    return f"{value:,}"


def lang_color(name: str) -> str:
    if name in LANG_COLORS:
        return LANG_COLORS[name]
    digest = 0
    for char in name:
        digest = (digest * 33 + ord(char)) & 0xFFFFFFFF
    return FALLBACK_COLORS[digest % len(FALLBACK_COLORS)]


def luminance(color: str) -> float:
    red = int(color[1:3], 16)
    green = int(color[3:5], 16)
    blue = int(color[5:7], 16)
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255


def icon_markup(name: str, x: float, y: float, fill: str, size: float = 16) -> str:
    scale = size / 16
    transform = f"translate({x:g},{y:g})"
    if scale != 1:
        transform += f" scale({scale:.4f})"
    lines = [
        f'    <g transform="{transform}" fill="{fill}" fill-rule="evenodd">',
    ]
    for path in ICONS[name]:
        lines.append(f'      <path d="{path}"/>')
    lines.append("    </g>")
    return "\n".join(lines)


def text_markup(
    x: float,
    y: float,
    content: str,
    fill: str,
    *,
    size: float = 14,
    weight: int = 400,
    anchor: str = "start",
) -> str:
    return (
        f'    <text x="{x:g}" y="{y:g}" fill="{fill}" font-size="{size:g}" '
        f'font-weight="{weight}" text-anchor="{anchor}" dominant-baseline="middle">'
        f"{svg_escape(content)}</text>"
    )


def svg_document(width: int, height: int, title: str, desc: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc" '
        f'font-family="{FONT}">\n'
        f"  <title id=\"title\">{svg_escape(title)}</title>\n"
        f"  <desc id=\"desc\">{svg_escape(desc)}</desc>\n"
        f"{body}\n"
        "</svg>\n"
    )


def render_stats(stats: dict, theme_name: str) -> str:
    theme = THEMES[theme_name]
    width, height = 224, 184
    rows = (
        ("star", "Total Stars", fmt_int(stats["stars"])),
        ("repo", "Public Repos", fmt_int(stats["public_repos"])),
        ("people", "Followers", fmt_int(stats["followers"])),
        ("commit", stats["activity_label"], fmt_int(stats["activity"])),
        ("pr", "Pull Requests", fmt_int(stats["pull_requests"])),
        ("issue", "Issues", fmt_int(stats["issues"])),
    )
    pad_y = 14
    row_h = 26
    parts = []
    for index, (icon_name, label, value) in enumerate(rows):
        center = pad_y + row_h / 2 + index * row_h
        parts.append(icon_markup(icon_name, 8, center - 8, theme["icon"], 16))
        parts.append(text_markup(32, center, label, theme["muted"], size=14))
        parts.append(
            text_markup(width - 12, center, value, theme["text"], size=14, weight=700, anchor="end")
        )
    desc = (
        f"{stats['login']}: {rows[0][2]} stars, {rows[1][2]} public repositories, "
        f"{rows[2][2]} followers, {rows[3][2]} {rows[3][1].lower()}, "
        f"{rows[4][2]} pull requests, {rows[5][2]} issues."
    )
    return svg_document(width, height, "GitHub stats", desc, "\n".join(parts))


def render_languages(stats: dict, theme_name: str) -> str:
    theme = THEMES[theme_name]
    ranked = stats["languages"]
    total = sum(count for _name, count in ranked)
    shown = ranked[:TOP_LANGUAGES]
    width = 420
    title = "Most Used Languages"

    if not shown or total <= 0:
        body = "\n".join(
            [
                text_markup(16, 28, title, theme["text"], size=15, weight=600),
                text_markup(16, 64, "No public code yet", theme["muted"], size=14),
            ]
        )
        return svg_document(width, 96, "Top languages", f"{stats['login']} has no public language data.", body)

    columns = 2
    row_count = (len(shown) + columns - 1) // columns
    height = 58 + row_count * 28 + 14
    bar_x, bar_y, bar_w, bar_h = 16, 38, width - 32, 8
    other_bytes = total - sum(count for _name, count in shown)
    segments: list[tuple[str, int]] = list(shown)
    proportional_total = total
    if other_bytes > 0 and other_bytes / total < 0.01:
        proportional_total = total - other_bytes
    elif other_bytes > 0:
        segments.append(("Other", other_bytes))

    parts = [
        text_markup(16, 20, title, theme["text"], size=15, weight=600),
        "  <defs>",
        f'    <clipPath id="lang-bar"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="4" ry="4"/></clipPath>',
        "  </defs>",
        '  <g clip-path="url(#lang-bar)">',
    ]
    cursor = float(bar_x)
    for index, (name, count) in enumerate(segments):
        if index == len(segments) - 1:
            segment_w = bar_x + bar_w - cursor
        else:
            segment_w = bar_w * (count / proportional_total)
        color = theme["other"] if name == "Other" else lang_color(name)
        parts.append(
            f'    <rect x="{cursor:.2f}" y="{bar_y}" width="{max(segment_w, 0):.2f}" height="{bar_h}" fill="{color}"/>'
        )
        cursor += segment_w
    parts.append("  </g>")

    for index, (name, count) in enumerate(shown):
        column = index % columns
        row = index // columns
        center = 70 + row * 28
        origin = 16 + column * 202
        color = lang_color(name)
        stroke = ""
        if luminance(color) > 0.72:
            stroke = f' stroke="{theme["dot_stroke"]}" stroke-width="1"'
        parts.append(
            f'  <circle cx="{origin + 5}" cy="{center}" r="4.5" fill="{color}"{stroke}/>'
        )
        parts.append(text_markup(origin + 16, center, name, theme["text"], size=13, weight=500))
        percent = 100.0 * count / total
        parts.append(
            text_markup(
                origin + 186,
                center,
                f"{percent:.1f}%",
                theme["muted"],
                size=12,
                anchor="end",
            )
        )

    summary = ", ".join(f"{name} {100.0 * count / total:.1f}%" for name, count in shown)
    return svg_document(width, height, "Top languages", f"Top languages for {stats['login']}: {summary}.", "\n".join(parts))


def write_cards(stats: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "github-stats.svg": render_stats(stats, "light"),
        "github-stats-dark.svg": render_stats(stats, "dark"),
        "top-langs.svg": render_languages(stats, "light"),
        "top-langs-dark.svg": render_languages(stats, "dark"),
    }
    written = []
    for name, contents in files.items():
        path = out_dir / name
        path.write_text(contents, encoding="utf-8", newline="\n")
        written.append(path)
    return written


def main() -> int:
    login = resolve_login()
    token = resolve_token()
    out_dir = Path(os.environ.get("STATS_OUT", "assets"))
    try:
        stats = load_stats(login, token)
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    paths = write_cards(stats, out_dir)
    print(f"login: {stats['login']}")
    print(f"stars: {stats['stars']}")
    print(f"public_repos: {stats['public_repos']}")
    print(f"followers: {stats['followers']}")
    print(f"activity: {stats['activity']} ({stats['activity_label']}, {stats['activity_source']})")
    print(f"pull_requests: {stats['pull_requests']}")
    print(f"issues: {stats['issues']}")
    print("languages:")
    total = sum(count for _name, count in stats["languages"]) or 1
    for name, count in stats["languages"][:TOP_LANGUAGES]:
        print(f"  {name}: {count} ({100.0 * count / total:.1f}%)")
    for path in paths:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
