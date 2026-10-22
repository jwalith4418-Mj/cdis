"""Regression + hardening tests for the production refactor.

Covers the security, correctness, and data-integrity fixes that the original
suite did not exercise: admin authorization, certificate false-linking, cross-user
isolation, upload limits, version uniqueness, the fact state machine, structured
error envelopes, and security headers.
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

CERT_RESUME = """Ada Fresh
ada@example.com

SKILLS
Git, Python

CERTIFICATIONS
- Digital Marketing Professional Certificate
"""

SIMPLE_RESUME = """Ben Fresh
ben@example.com

SKILLS
Python, FastAPI, Docker

PROJECTS
- A small service
"""

# Body-only mention of Kafka -> parser_b -> a guaranteed pending fact.
STATE_RESUME = """Cara Fresh
cara@example.com
Tinkered with Kafka event streaming on the side.

SKILLS
Python
"""

JD = ("Backend Engineer. Python and FastAPI required. Docker required. "
      "Kubernetes a plus. SQL and Git expected.")


def _fresh_user(client):
    email = f"user-{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/auth/register",
                    json={"email": email, "name": "User", "password": "supersecret1"})
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ---------- auth / authorization ----------

def test_non_admin_cannot_toggle_kill_switch(client):
    headers = _fresh_user(client)
    r = client.post("/api/admin/llm-kill-switch", headers=headers, json={"llm_down": True})
    assert r.status_code == 403
    assert "trace_id" in r.json()  # consistent error envelope


def test_admin_can_toggle_kill_switch(client, admin_auth):
    r = client.post("/api/admin/llm-kill-switch", headers=admin_auth, json={"llm_down": False})
    assert r.status_code == 200 and r.json()["simulate_llm_down"] is False


# ---------- correctness: certificate must not false-link by substring ----------

def test_certificate_does_not_substring_link_to_git(client):
    headers = _fresh_user(client)
    client.post("/api/twin/resume", json={"text": CERT_RESUME}, headers=headers)
    card = client.get("/api/twin/scorecard", headers=headers).json()
    git = next(r for r in card["rows"] if r["skill"] == "Git")
    # "Digital Marketing ... Certificate" must NOT attach to Git ('git' in 'digital').
    assert git["score"] == 0
    assert all(e["type"] != "certificate" for e in git["evidence"])


# ---------- multi-tenant isolation ----------

def test_decisions_are_isolated_between_users(client):
    a, b = _fresh_user(client), _fresh_user(client)
    client.post("/api/twin/resume", json={"text": SIMPLE_RESUME}, headers=a)
    dec = client.post("/api/decisions/gap-analysis", headers=a,
                      json={"jd_text": JD, "target_label": "Backend"}).json()
    did = dec["decision_id"]
    # Owner can read; a different user cannot (404, not 403 — no existence leak).
    assert client.get(f"/api/audit/{did}", headers=a).status_code == 200
    assert client.get(f"/api/audit/{did}", headers=b).status_code == 404
    assert client.post(f"/api/audit/{did}/replay", headers=b).status_code == 404


# ---------- upload limits ----------

def test_oversized_upload_rejected(client):
    headers = _fresh_user(client)
    big = b"a" * 5000  # conftest caps MAX_UPLOAD_BYTES at 4096
    r = client.post("/api/twin/resume/file", headers=headers,
                    files={"file": ("resume.txt", big, "text/plain")})
    assert r.status_code == 413
    assert "trace_id" in r.json()


# ---------- fact state machine ----------

def test_rejected_fact_cannot_be_reconfirmed(client):
    headers = _fresh_user(client)
    client.post("/api/twin/resume", json={"text": STATE_RESUME}, headers=headers)
    twin = client.get("/api/twin", headers=headers).json()
    pend = [f for f in twin["pending"] if f["value"] == "Kafka"]
    assert pend, "expected a pending Kafka fact"
    fid = pend[0]["id"]
    assert client.post(f"/api/twin/facts/{fid}/reject", headers=headers).status_code == 200
    # Re-confirming a rejected fact is refused (no silent resurrection).
    assert client.post(f"/api/twin/facts/{fid}/confirm", headers=headers).status_code == 409
    # Rejecting twice is also refused.
    assert client.post(f"/api/twin/facts/{fid}/reject", headers=headers).status_code == 409


# ---------- data integrity: version uniqueness constraint is real ----------

def test_resume_version_unique_constraint(client):
    from sqlalchemy import select

    from app import database
    from app.models import ResumeVersion, User

    headers = _fresh_user(client)
    me = client.get("/api/twin", headers=headers).json()
    with database.SessionLocal() as db:
        uid = db.execute(select(User).where(User.email == me["email"])).scalar_one().id
        db.add(ResumeVersion(user_id=uid, version=1, content="a", target_label="master"))
        db.commit()
        db.add(ResumeVersion(user_id=uid, version=1, content="b", target_label="master"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


# ---------- observability: headers + envelope ----------

def test_security_headers_present(client):
    r = client.get("/api/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "X-Trace-Id" in r.headers


def test_unauthenticated_error_has_trace_id(client):
    r = client.get("/api/twin")
    assert r.status_code == 401
    body = r.json()
    assert body["trace_id"] and "detail" in body


# ---------- AI workflow: grounding guard + evidence/confidence/explanation ----------

def test_gap_output_ships_evidence_confidence_explanation(client):
    headers = _fresh_user(client)
    client.post("/api/twin/resume", json={"text": SIMPLE_RESUME}, headers=headers)
    out = client.post("/api/decisions/gap-analysis", headers=headers,
                      json={"jd_text": JD, "target_label": "Backend"}).json()
    assert out["explanation"]
    assert out["confidence"] in ("High", "Medium", "Low") and out["confidence_basis"]
    assert isinstance(out["evidence"], list) and out["evidence"]
    assert {"skill", "jd_mentions", "evidence_score", "status"} <= set(out["evidence"][0])


def test_llm_grounding_guard_rejects_fabricated_or_altered_numbers():
    from app.services.decision import is_grounded
    tmpl = "Alignment 72/100 for Backend. The gap is concentrated in: Docker."
    assert is_grounded(tmpl, "You're at 72/100 for Backend; Docker is the main gap.")
    assert is_grounded(tmpl, "Docker is your biggest gap for this Backend role.")  # drops nums
    assert not is_grounded(tmpl, "You have an 85% chance for this Backend role.")  # invented 85
    assert not is_grounded(tmpl, "Alignment 75/100 — close the Docker gap.")  # altered 72->75
    assert not is_grounded(tmpl, "")  # empty
    assert not is_grounded(tmpl, "x" * (len(tmpl) + 300))  # runaway length
    # worded outcome/probability claims carry no new digit but must still be rejected
    assert not is_grounded(tmpl, "You're basically guaranteed an offer here.")
    assert not is_grounded(tmpl, "You'll likely get this Backend role.")


# ---------- security: auth enumeration, privacy, headers, throttle ----------

def test_login_gives_no_user_enumeration_signal(client):
    # Wrong password on a real account and login for a nonexistent account must be
    # indistinguishable (same status + detail) — no account-existence oracle.
    client.post("/api/auth/register",
                json={"email": "enum@example.com", "name": "E", "password": "supersecret1"})
    wrong = client.post("/api/auth/login",
                        json={"email": "enum@example.com", "password": "wrongwrong1"})
    missing = client.post("/api/auth/login",
                          json={"email": "nobody-here@example.com", "password": "wrongwrong1"})
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json()["detail"] == missing.json()["detail"]


def test_account_export_returns_callers_data(client):
    headers = _fresh_user(client)
    client.post("/api/twin/resume", json={"text": SIMPLE_RESUME}, headers=headers)
    exp = client.get("/api/account/export", headers=headers).json()
    assert exp["profile"]["email"] and "twin_events" in exp and "decisions" in exp
    assert exp["twin_events"], "export should include the user's events"


def test_account_delete_requires_correct_password(client):
    headers = _fresh_user(client)
    bad = client.post("/api/account/delete", headers=headers, json={"password": "not-it-1234"})
    assert bad.status_code == 403
    assert client.get("/api/twin", headers=headers).status_code == 200  # still usable


def test_account_delete_hard_deletes_and_revokes(client):
    email = f"del-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/register",
                    json={"email": email, "name": "D", "password": "supersecret1"})
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    client.post("/api/twin/resume", json={"text": SIMPLE_RESUME}, headers=headers)
    gone = client.post("/api/account/delete", headers=headers, json={"password": "supersecret1"})
    assert gone.status_code == 200 and gone.json()["deleted"] is True
    assert client.get("/api/twin", headers=headers).status_code == 401  # token now dangles


def test_csp_and_clickjacking_headers_present(client):
    h = client.get("/api/health").headers
    csp = h.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in csp and "default-src 'self'" in csp
    assert h.get("X-Content-Type-Options") == "nosniff"


def test_auth_endpoints_are_throttled(client):
    from app import config
    original = config.settings.auth_rate_limit_per_minute
    config.settings.auth_rate_limit_per_minute = 3
    try:
        codes = [client.post("/api/auth/login",
                             json={"email": "x@example.com", "password": "nope12345"}).status_code
                 for _ in range(12)]
        assert 429 in codes, "auth brute-force should be rate limited"
    finally:
        config.settings.auth_rate_limit_per_minute = original


# ---------- value gaps: outcome funnel + GitHub verified evidence ----------

def test_outcome_funnel_and_north_star(client):
    h = _fresh_user(client)
    a = client.post("/api/outcomes", headers=h, json={"target_role": "Backend"}).json()
    assert a["status"] == "applied"
    client.patch(f"/api/outcomes/{a['id']}", headers=h, json={"status": "interview"})
    out = client.get("/api/outcomes", headers=h).json()
    assert out["north_star"]["advanced_beyond_applied"] == 1


def test_github_mapping_is_pure_and_verified():
    from app.services.github import repos_to_evidence
    ev = repos_to_evidence([
        {"language": "Python", "name": "api", "description": "FastAPI service",
         "html_url": "https://github.com/x/api", "topics": ["docker"]},
        {"fork": True, "language": "Go", "name": "z", "html_url": "https://github.com/x/z"},
    ])
    skills = {e["skill"] for e in ev}
    assert {"Python", "FastAPI", "Docker"} <= skills
    assert all(e["type"] == "github_repo" for e in ev)


def test_livez_is_dbless_and_unauthenticated(client):
    r = client.get("/api/livez")
    assert r.status_code == 200 and r.json()["status"] == "alive"


def test_github_evidence_rejects_gamed_and_archived_repos():
    from app.services.github import repos_to_evidence
    ev = repos_to_evidence([
        # empty repo, no language/topics, skills only in a crafted name -> nothing
        {"name": "python-docker-aws-react", "description": "kubernetes tensorflow",
         "html_url": "https://github.com/x/gamed"},
        # archived real repo -> excluded
        {"language": "Python", "name": "old", "archived": True,
         "html_url": "https://github.com/x/old"},
        # real substantive repo -> counts
        {"language": "Python", "name": "svc", "topics": ["docker"],
         "html_url": "https://github.com/x/svc"},
    ])
    refs = {(e["skill"], e["reference"]) for e in ev}
    assert not any(r[1].endswith(("/gamed", "/old")) for r in refs)  # gamed + archived out
    assert ("Python", "https://github.com/x/svc") in refs
    assert ("Docker", "https://github.com/x/svc") in refs


def test_github_import_builds_scorecard(client, monkeypatch):
    import app.services.github as gh
    monkeypatch.setattr(gh, "fetch_repos", lambda u: [
        {"language": "Python", "name": "svc", "description": "",
         "html_url": "https://github.com/x/svc", "topics": []}])
    h = _fresh_user(client)
    r = client.post("/api/twin/evidence/github", headers=h, json={"username": "octocat"})
    assert r.status_code == 201 and r.json()["skills_added"] >= 1
    card = client.get("/api/twin/scorecard", headers=h).json()
    assert any(row["skill"] == "Python" and row["score"] >= 30 for row in card["rows"])
