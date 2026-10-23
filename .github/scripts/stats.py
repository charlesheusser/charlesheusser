"""Gera dist/stats.svg e dist/streak.svg com estatísticas do GitHub, incluindo contribuições privadas.

Usa GH_TOKEN (PAT com escopo `repo` + `read:org` para contar commits em repositórios
privados por tipo) ou, na falta dele, o GITHUB_TOKEN do Actions — nesse caso as
contribuições privadas aparecem agregadas em "Contribuições privadas".
"""
import json
import os
import urllib.request
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

USER = os.environ["STATS_USER"]
TOKEN = os.environ["GH_TOKEN"]
OUT = os.environ.get("STATS_OUT", "dist/stats.svg")
STREAK_OUT = os.path.join(os.path.dirname(OUT), "streak.svg")

COUNTS = """
  totalCommitContributions
  totalPullRequestContributions
  totalIssueContributions
  totalPullRequestReviewContributions
  restrictedContributionsCount
  contributionCalendar { totalContributions }
"""


def gql(query, **variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]


def collect():
    data = gql(
        f"""query($login: String!) {{
          user(login: $login) {{
            name
            followers {{ totalCount }}
            repositories(ownerAffiliations: OWNER, first: 100) {{ nodes {{ stargazerCount }} }}
            contributionsCollection {{
              {COUNTS}
              totalRepositoriesWithContributedCommits
              contributionYears
            }}
          }}
        }}""",
        login=USER,
    )["user"]
    year = data["contributionsCollection"]

    all_time = {"commits": 0, "contributions": 0}
    days = {}
    for y in year["contributionYears"]:
        c = gql(
            f"""query($login: String!, $from: DateTime!, $to: DateTime!) {{
              user(login: $login) {{ contributionsCollection(from: $from, to: $to) {{
                {COUNTS}
                contributionCalendar {{ weeks {{ contributionDays {{ date contributionCount }} }} }}
              }} }}
            }}""",
            login=USER,
            **{"from": f"{y}-01-01T00:00:00Z", "to": f"{y}-12-31T23:59:59Z"},
        )["user"]["contributionsCollection"]
        all_time["commits"] += c["totalCommitContributions"]
        all_time["contributions"] += c["contributionCalendar"]["totalContributions"]
        for week in c["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[date.fromisoformat(d["date"])] = d["contributionCount"]

    return {
        "name": data["name"] or USER,
        "stars": sum(r["stargazerCount"] for r in data["repositories"]["nodes"]),
        "followers": data["followers"]["totalCount"],
        "year": year,
        "all_time": all_time,
        "days": days,
    }


def streaks(days):
    today = datetime.now(timezone.utc).date()
    active = sorted(d for d, n in days.items() if n > 0 and d <= today)

    longest = (0, None, None)
    run_start = prev = None
    for d in active:
        if prev is None or d - prev != timedelta(days=1):
            run_start = d
        prev = d
        length = (d - run_start).days + 1
        if length > longest[0]:
            longest = (length, run_start, d)

    # Hoje sem contribuição ainda não quebra a sequência.
    current = (0, None, None)
    if active and active[-1] >= today - timedelta(days=1):
        end = start = active[-1]
        while days.get(start - timedelta(days=1), 0) > 0:
            start -= timedelta(days=1)
        current = ((end - start).days + 1, start, end)

    return {
        "total": sum(days.values()),
        "first": active[0] if active else None,
        "current": current,
        "longest": longest,
    }


def fmt_date(d):
    return d.strftime("%d/%m/%Y") if d else "—"


def fmt_range(r):
    _, start, end = r
    if not start:
        return "—"
    return fmt_date(start) if start == end else f"{fmt_date(start)} – {fmt_date(end)}"


def render_streak(s):
    st = streaks(s["days"])
    cols = [
        (f"{st['total']:,}".replace(",", "."), "Total de contribuições", f"{fmt_date(st['first'])} – hoje"),
        (str(st["current"][0]), "Sequência atual", fmt_range(st["current"])),
        (str(st["longest"][0]), "Maior sequência", fmt_range(st["longest"])),
    ]
    body = "\n".join(
        f'<text x="{x}" y="74" class="num" text-anchor="middle">{escape(n)}</text>'
        f'<text x="{x}" y="122" class="label" text-anchor="middle">{escape(label)}</text>'
        f'<text x="{x}" y="146" class="sub" text-anchor="middle">{escape(sub)}</text>'
        for x, (n, label, sub) in zip((83, 250, 417), cols)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="500" height="195" viewBox="0 0 500 195" role="img" aria-label="Sequência de contribuições de {escape(s['name'])}">
<style>
  .num {{ font: 700 28px 'Segoe UI', Ubuntu, Sans-Serif; fill: #c9d1d9; }}
  .label {{ font: 600 13px 'Segoe UI', Ubuntu, Sans-Serif; fill: #58a6ff; }}
  .sub {{ font: 400 11px 'Segoe UI', Ubuntu, Sans-Serif; fill: #8b949e; }}
</style>
<rect x="0.5" y="0.5" rx="6" width="499" height="194" fill="#0d1117" stroke="#30363d"/>
<line x1="166" y1="30" x2="166" y2="165" stroke="#30363d"/>
<line x1="334" y1="30" x2="334" y2="165" stroke="#30363d"/>
<circle cx="250" cy="64" r="30" fill="none" stroke="#58a6ff" stroke-width="4"/>
{body}
<text x="250" y="182" class="sub" text-anchor="middle">Inclui contribuições privadas</text>
</svg>
"""


def render(s):
    y = s["year"]
    private = y["restrictedContributionsCount"]
    if private:
        # Sem acesso aos repositórios privados a API só informa o total privado,
        # sem separar por tipo; linhas por tipo contariam apenas o que é público.
        rows = [
            ("Contribuições (último ano)", y["contributionCalendar"]["totalContributions"]),
            ("Contribuições privadas (último ano)", private),
            ("Commits públicos (último ano)", y["totalCommitContributions"]),
            ("Repositórios públicos com commits", y["totalRepositoriesWithContributedCommits"]),
            ("Contribuições totais (todos os anos)", s["all_time"]["contributions"]),
            ("Estrelas recebidas", s["stars"]),
        ]
    else:
        rows = [
            ("Contribuições (último ano)", y["contributionCalendar"]["totalContributions"]),
            ("Commits (último ano)", y["totalCommitContributions"]),
            ("Pull requests (último ano)", y["totalPullRequestContributions"]),
            ("Code reviews (último ano)", y["totalPullRequestReviewContributions"]),
            ("Issues (último ano)", y["totalIssueContributions"]),
            ("Repositórios com commits (último ano)", y["totalRepositoriesWithContributedCommits"]),
            ("Contribuições totais (todos os anos)", s["all_time"]["contributions"]),
            ("Estrelas recebidas", s["stars"]),
        ]

    line_h, top = 25, 62
    height = top + line_h * len(rows) + 10
    body = "\n".join(
        f'<text x="25" y="{top + i * line_h}" class="label">{escape(label)}:</text>'
        f'<text x="425" y="{top + i * line_h}" class="value" text-anchor="end">{value:,}</text>'.replace(",", ".")
        for i, (label, value) in enumerate(rows)
    )
    updated = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="450" height="{height + 18}" viewBox="0 0 450 {height + 18}" role="img" aria-label="Estatísticas do GitHub de {escape(s['name'])}">
<style>
  .title {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: #58a6ff; }}
  .label {{ font: 600 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: #c9d1d9; }}
  .value {{ font: 700 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: #58a6ff; }}
  .foot {{ font: 400 11px 'Segoe UI', Ubuntu, Sans-Serif; fill: #8b949e; }}
</style>
<rect x="0.5" y="0.5" rx="6" width="449" height="{height + 17}" fill="#0d1117" stroke="#30363d"/>
<text x="25" y="32" class="title">Estatísticas de {escape(s['name'])}</text>
{body}
<text x="25" y="{height + 6}" class="foot">Inclui contribuições privadas · atualizado em {updated}</text>
</svg>
"""


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    stats = collect()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(render(stats))
    with open(STREAK_OUT, "w", encoding="utf-8") as f:
        f.write(render_streak(stats))
    print(f"wrote {OUT} and {STREAK_OUT}")
