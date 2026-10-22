"""Turn a user's real public GitHub work into VERIFIED evidence — the activation
moment: the Evidence Scorecard builds itself from shipped code, not typed claims."""
import httpx

from ..config import settings
from .parser import match_skills


def repos_to_evidence(repos: list[dict]) -> list[dict]:
    """Pure mapping (no network): repo -> canonical skills as github_repo evidence.

    A repo counts as VERIFIED evidence only if it is real, code-backed work:
      - not a fork and not archived (someone else's / abandoned work), and
      - GitHub detected a `language` OR the author applied `topics`.
    The language/topics gate is the anti-gaming control: an empty repo whose only
    skill signal is a crafted name ("python-docker-aws-react") has no detected
    language and no topics, so it mints nothing. For repos that clear the gate,
    matching still spans language/name/description/topics so real projects keep
    full recall (a Python FastAPI repo still credits FastAPI from its description).
    """
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for r in repos:
        if r.get("fork") or r.get("archived"):
            continue
        language = r.get("language")
        topics = r.get("topics", []) or []
        if not language and not topics:
            continue  # no code-backed signal — refuse to credit a name-only repo
        parts = [language, r.get("name"), r.get("description"), " ".join(topics)]
        text = " ".join(str(p) for p in parts if p)
        url = r.get("html_url", "")
        for skill in match_skills(text):
            key = (skill, url)
            if key not in seen:
                seen.add(key)
                out.append({"skill": skill, "type": "github_repo", "reference": url})
    return out


def fetch_repos(username: str) -> list[dict]:
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    with httpx.Client(timeout=8.0) as c:
        resp = c.get(f"https://api.github.com/users/{username}/repos",
                     params={"per_page": 100, "sort": "pushed"}, headers=headers)
        resp.raise_for_status()
        return resp.json()
