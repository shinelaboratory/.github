import json
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Tuple

ORG = "shinelaboratory"
README_PATH = "profile/README.md"

REPOS = [
    "cognitive-compass",
    "cogsec-hid-testbed",
    "sensor_analysis_tools",
    "obs-lab-manager",
    "muri_survey_analysis",
    "cogsec-web-socket-lsl-bridge"


]

USER_META = {
    # faculty / staff
    "Lhirshfield": {"name": "Dr. Leanne Hirshfield", "role": "Lab Director"},
    "JamesCrum": {"name": "James Crum", "role": "Research Scientist I"},
    "sduyr": {"name": "Senjuti Dutta", "role": "Postdoctoral Research Fellow"},

    # students
    "aarnol": {"name": "Alex Arnold", "role": "PhD Student"},
    "m-middleton": {"name": "Michael Middleton", "role": "PhD Student"},
    "emilydoherty": {"name": "Emily Doherty", "role": "PhD Candidate"},
    "dita-hss": {"name": "Amanda Hernandez", "role": "PhD Student"},
    "nicole.jone": {"name": "Nicole Jone", "role": "PhD Student"},
    "ZCKaufman": {"name": "Zachary Kaufman", "role": "PhD Student"},
    "melissa.mclain": {"name": "Melissa McLain", "role": "PhD Student"},
    "Jalynnn": {"name": "Jalynn Nicoly", "role": "PhD Student"},
    "cara-spencer": {"name": "Cara Spencer", "role": "PhD Candidate"},
    "cgenevier": {"name": "Charlotte Wyman", "role": "PhD Student"},
}


ALWAYS_INCLUDE_LOGINS = [
    "Lhirshfield",
    "JamesCrum",
    "sduyr",
    "aarnol",
    "m-middleton",
    "emilydoherty",
    "dita-hss",
    "nicole.jone",
    "ZCKaufman",
    "melissa.mclain",
    "Jalynnn",
    "cara-spencer",
    "cgenevier",
]


EXCLUDED_LOGINS = {
    "github-actions[bot]",
    "dependabot[bot]",
}

START_MARKER = "<!-- PEOPLE_WALL_START -->"
END_MARKER = "<!-- PEOPLE_WALL_END -->"

TOKEN = os.environ.get("ORG_READ_TOKEN") or os.environ.get("GITHUB_TOKEN")


def gh_api(url: str):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "shine-contributors-wall-script")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")

    with urllib.request.urlopen(req) as resp:
        data = resp.read().decode("utf-8")
        return json.loads(data), resp.headers


def paginate(url: str) -> List[dict]:
    items = []
    next_url = url

    while next_url:
        data, headers = gh_api(next_url)
        if isinstance(data, list):
            items.extend(data)
        else:
            raise RuntimeError(f"Expected list from GitHub API, got: {type(data)}")

        link_header = headers.get("Link", "")
        next_url = None
        if link_header:
            parts = [p.strip() for p in link_header.split(",")]
            for part in parts:
                if 'rel="next"' in part:
                    start = part.find("<") + 1
                    end = part.find(">")
                    next_url = part[start:end]
                    break

        time.sleep(0.1)

    return items


def get_repo_contributors(org: str, repo: str) -> List[dict]:
    url = f"https://api.github.com/repos/{urllib.parse.quote(org)}/{urllib.parse.quote(repo)}/contributors?per_page=100"
    return paginate(url)


def get_user(login: str) -> dict:
    url = f"https://api.github.com/users/{urllib.parse.quote(login)}"
    data, _ = gh_api(url)
    return data


def collect_contributors(org: str, repos: List[str]) -> Dict[str, dict]:
    merged: Dict[str, dict] = {}

    for repo in repos:
        print(f"Fetching contributors for {org}/{repo}...", file=sys.stderr)
        contributors = get_repo_contributors(org, repo)

        for c in contributors:
            login = c.get("login")
            if not login:
                continue

            if login in EXCLUDED_LOGINS or login.endswith("[bot]"):
                continue

            if login not in merged:
                merged[login] = {
                    "login": login,
                    "contributions": 0,
                    "repos": set(),
                }

            merged[login]["contributions"] += c.get("contributions", 0)
            merged[login]["repos"].add(repo)

    return merged


def enrich_users(contributors: Dict[str, dict]) -> List[dict]:
    people = []

    for login, info in contributors.items():
        try:
            user = get_user(login)
        except Exception as e:
            print(f"Warning: failed to fetch user {login}: {e}", file=sys.stderr)
            user = {}

        meta = USER_META.get(login, {})
        name = meta.get("name") or user.get("name") or login
        role = meta.get("role", "")
        avatar_url = user.get("avatar_url") or f"https://github.com/{login}.png"
        html_url = user.get("html_url") or f"https://github.com/{login}"

        people.append({
            "login": login,
            "name": name,
            "role": role,
            "avatar_url": avatar_url,
            "html_url": html_url,
            "contributions": info["contributions"],
            "repos": sorted(info["repos"]),
        })

        time.sleep(0.05)

    people.sort(key=lambda x: (-x["contributions"], x["login"].lower()))
    return people


def add_manual_people(people: List[dict]) -> List[dict]:
    """Ensure ALWAYS_INCLUDE_LOGINS appear even with 0 contributions."""
    existing_logins = {p["login"] for p in people}

    for login in ALWAYS_INCLUDE_LOGINS:
        if login in existing_logins:
            continue

        try:
            user = get_user(login)
        except Exception as e:
            print(f"Warning: failed to fetch manual user {login}: {e}", file=sys.stderr)
            user = {}

        meta = USER_META.get(login, {})
        name = meta.get("name") or user.get("name") or login
        role = meta.get("role", "")
        avatar_url = user.get("avatar_url") or f"https://github.com/{login}.png"
        html_url = user.get("html_url") or f"https://github.com/{login}"

        people.append({
            "login": login,
            "name": name,
            "role": role,
            "avatar_url": avatar_url,
            "html_url": html_url,
            "contributions": 0,
            "repos": [],
        })

    # Resort so manual entries with 0 contributions are at the end,
    # still keeping a consistent ordering.
    people.sort(key=lambda x: (-x["contributions"], x["login"].lower()))
    return people


def build_wall(people: List[dict], per_row: int = 4) -> str:
    if not people:
        return "_No contributors found._"

    lines = []
    lines.append("<table>")
    for i in range(0, len(people), per_row):
        chunk = people[i:i + per_row]
        lines.append("  <tr>")
        for person in chunk:
            title = f'{person["login"]}'
            role_html = f'<br /><sub>{escape_html(person["role"])}</sub>' if person["role"] else ""

            cell = (
                f'    <td align="center" valign="top" width="25%">'
                f'<a href="{person["html_url"]}" title="{escape_html(title)}">'
                f'<img src="{person["avatar_url"]}" width="90" alt="{escape_html(person["login"])}" />'
                f'<br /><sub><b>{escape_html(person["name"])}</b></sub>'
                f'</a>'
                f'{role_html}'
                f'</td>'
            )
            lines.append(cell)
        lines.append("  </tr>")
    lines.append("</table>")
    return "\n".join(lines)


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def replace_section(readme_text: str, new_section: str) -> str:
    if START_MARKER not in readme_text or END_MARKER not in readme_text:
        raise RuntimeError("README markers not found.")

    before, rest = readme_text.split(START_MARKER, 1)
    _, after = rest.split(END_MARKER, 1)

    return before + START_MARKER + "\n" + new_section + "\n" + END_MARKER + after


def main():
    if not os.path.exists(README_PATH):
        raise FileNotFoundError(f"README not found at {README_PATH}")

    contributors = collect_contributors(ORG, REPOS)
    people = enrich_users(contributors)
    people = add_manual_people(people)
    wall = build_wall(people)

    with open(README_PATH, "r", encoding="utf-8") as f:
        readme = f.read()

    updated = replace_section(readme, wall)

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(updated)

    print(f"Updated {README_PATH} with {len(people)} contributors.")


if __name__ == "__main__":
    main()