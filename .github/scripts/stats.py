"""Gera dist/stats.svg com estatísticas do GitHub, incluindo contribuições privadas.

Usa GH_TOKEN (PAT com escopo `repo` + `read:org` para contar commits em repositórios
privados por tipo) ou, na falta dele, o GITHUB_TOKEN do Actions — nesse caso as
contribuições privadas aparecem agregadas em "Contribuições privadas".
"""
import json
import os
import urllib.request
from datetime import datetime, timezone
from xml.sax.saxutils import escape

USER = os.environ["STATS_USER"]
TOKEN = os.environ["GH_TOKEN"]
OUT = os.environ.get("STATS_OUT", "dist/stats.svg")

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
    for y in year["contributionYears"]:
        c = gql(
            f"""query($login: String!, $from: DateTime!, $to: DateTime!) {{
              user(login: $login) {{ contributionsCollection(from: $from, to: $to) {{ {COUNTS} }} }}
            }}""",
            login=USER,
            **{"from": f"{y}-01-01T00:00:00Z", "to": f"{y}-12-31T23:59:59Z"},
        )["user"]["contributionsCollection"]
        all_time["commits"] += c["totalCommitContributions"]
        all_time["contributions"] += c["contributionCalendar"]["totalContributions"]

    return {
        "name": data["name"] or USER,
        "stars": sum(r["stargazerCount"] for r in data["repositories"]["nodes"]),
        "followers": data["followers"]["totalCount"],
        "year": year,
        "all_time": all_time,
    }


def render(s):
    y = s["year"]
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
    if y["restrictedContributionsCount"]:
        rows.insert(2, ("Contribuições privadas (último ano)", y["restrictedContributionsCount"]))

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
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(render(collect()))
    print(f"wrote {OUT}")
