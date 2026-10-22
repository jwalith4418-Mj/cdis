"""End-to-end tests for the Blueprint §12 vertical slice.

Ordered as the demo runs: auth → ingest (HITL tiers) → confirm → evidence
scorecard (certificate cap) → gap analysis (no probability, evidence-cited)
→ resume draft/diff/approve → decision replay → kill switch degradation.
"""
from .conftest import SAMPLE_JD, SAMPLE_RESUME

# ---------- auth ----------

def test_register_conflict_and_login(client):
    r = client.post("/api/auth/register", json={
        "email": "dup@example.com", "name": "Dup", "password": "supersecret1"})
    assert r.status_code == 201
    r = client.post("/api/auth/register", json={
        "email": "dup@example.com", "name": "Dup", "password": "supersecret1"})
    assert r.status_code == 409
    r = client.post("/api/auth/login", json={"email": "dup@example.com",
                                             "password": "wrongpassword"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "dup@example.com",
                                             "password": "supersecret1"})
    assert r.status_code == 200 and "token" in r.json()


def test_endpoints_require_auth(client):
    for method, path in (("get", "/api/twin"), ("get", "/api/twin/scorecard"),
                         ("get", "/api/audit")):
        assert getattr(client, method)(path).status_code == 401


# ---------- ingestion + HITL tiers ----------

def test_ingest_resume_hitl_tiers(client, auth):
    r = client.post("/api/twin/resume", json={"text": SAMPLE_RESUME}, headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert "parser_a" in body["stages_used"] and "parser_b" in body["stages_used"]
    by_value = {f["value"]: f for f in body["facts"]}
    # Skills section -> auto-accepted (>=0.8)
    assert by_value["Python"]["status"] == "accepted"
    assert by_value["Docker"]["status"] == "accepted"
    # Body-only mention -> pending confirmation (0.6-0.8)
    assert by_value["Kafka"]["status"] == "pending"
    # Quantified impact claim -> manual review (<0.6)
    impact = [f for f in body["facts"] if f["entity"] == "impact_claim"]
    assert impact and all(f["status"] == "manual_review" for f in impact)


def test_pending_facts_excluded_until_confirmed(client, auth):
    twin = client.get("/api/twin", headers=auth).json()
    accepted_skills = {f["value"] for f in twin["accepted"]["skill"]}
    assert "Kafka" not in accepted_skills and "Redis" not in accepted_skills
    kafka = next(f for f in twin["pending"] if f["value"] == "Kafka")
    r = client.post(f"/api/twin/facts/{kafka['id']}/confirm", headers=auth)
    assert r.status_code == 200
    twin = client.get("/api/twin", headers=auth).json()
    assert "Kafka" in {f["value"] for f in twin["accepted"]["skill"]}


def test_reject_fact(client, auth):
    twin = client.get("/api/twin", headers=auth).json()
    redis = next(f for f in twin["pending"] if f["value"] == "Redis")
    client.post(f"/api/twin/facts/{redis['id']}/reject", headers=auth)
    twin = client.get("/api/twin", headers=auth).json()
    assert "Redis" not in {f["value"] for f in twin["accepted"]["skill"]}
    assert all(f["value"] != "Redis" for f in twin["pending"])


def test_unreadable_file_falls_back_gracefully(client, auth):
    r = client.post("/api/twin/resume/file", headers=auth,
                    files={"file": ("scan.pdf", b"\x00\x01\x02", "application/pdf")})
    assert r.status_code == 422
    assert "manually" in r.json()["detail"]


# ---------- evidence scorecard ----------

def test_certificate_only_skill_capped_at_medium(client, auth):
    # Kubernetes was found only inside a certificate line -> parser B -> pending.
    twin = client.get("/api/twin", headers=auth).json()
    k8s_fact = next(f for f in twin["pending"] if f["value"] == "Kubernetes")
    client.post(f"/api/twin/facts/{k8s_fact['id']}/confirm", headers=auth)
    card = client.get("/api/twin/scorecard", headers=auth).json()
    rows = {r["skill"]: r for r in card["rows"]}
    # Its only evidence is the auto-linked certificate -> capped at Medium.
    k8s = rows["Kubernetes"]
    assert k8s["score"] <= 40 and k8s["band"] in ("Low", "Medium")  # never High
    assert "cap" in k8s["rule"].lower()
    # Even stacking certificates cannot break the ceiling.
    for i in range(4):
        client.post("/api/twin/evidence", headers=auth, json={
            "skill": "Kubernetes", "type": "certificate", "reference": f"K8s cert #{i}"})
    card = client.get("/api/twin/scorecard", headers=auth).json()
    k8s = next(r for r in card["rows"] if r["skill"] == "Kubernetes")
    assert k8s["score"] == 40 and k8s["band"] == "Medium"


def test_evidence_raises_score_with_citations(client, auth):
    r = client.post("/api/twin/evidence", headers=auth, json={
        "skill": "Python", "type": "github_repo",
        "reference": "https://github.com/example/climaverse"})
    assert r.status_code == 201
    client.post("/api/twin/evidence", headers=auth, json={
        "skill": "Python", "type": "deployed_artifact",
        "reference": "https://climaverse.example.com"})
    client.post("/api/twin/evidence", headers=auth, json={
        "skill": "Docker", "type": "project", "reference": "CropDoctor container stack"})
    card = client.get("/api/twin/scorecard", headers=auth).json()
    python = next(r for r in card["rows"] if r["skill"] == "Python")
    assert python["score"] >= 55 and len(python["evidence"]) >= 2
    assert client.post("/api/twin/evidence", headers=auth, json={
        "skill": "Cobol", "type": "blog", "reference": "x" * 10}).status_code == 404


# ---------- gap analysis ----------

def test_gap_analysis_contract(client, auth):
    r = client.post("/api/decisions/gap-analysis", headers=auth,
                    json={"jd_text": SAMPLE_JD, "target_label": "Backend Engineer (Cloud)"})
    assert r.status_code == 200
    out = r.json()
    assert "hiring_probability" not in str(out)          # banned field, anywhere
    assert 0 <= out["alignment_score"] <= 100
    assert out["confidence"] in ("High", "Medium", "Low") and out["confidence_basis"]
    assert out["limiting_factors"], "gaps must be surfaced"
    for f in out["limiting_factors"]:
        assert "×" in f["why"] and f["estimated_gain"] > 0  # evidence-cited
    inv = out["career_investment"]
    assert inv and inv["skill"] == out["limiting_factors"][0]["skill"]
    assert "estimate" in out["disclaimer"] and out["decision_id"]
    # No API key in test env -> rule engine primary, honestly reported
    assert out["fallback_used"] is True


def test_gap_analysis_requires_accepted_skills(client):
    r = client.post("/api/auth/register", json={
        "email": "empty@example.com", "name": "Empty", "password": "supersecret1"})
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    r = client.post("/api/decisions/gap-analysis", headers=headers,
                    json={"jd_text": SAMPLE_JD})
    assert r.status_code == 422


# ---------- resume engine ----------

def test_resume_draft_uses_only_accepted_facts(client, auth):
    r = client.post("/api/resume/draft", headers=auth,
                    json={"jd_text": SAMPLE_JD, "target_label": "Backend Engineer (Cloud)"})
    assert r.status_code == 200
    body = r.json()
    assert "Redis" not in body["draft"]                  # rejected fact stays out
    assert "40%" not in body["draft"]                    # unverified claim stays out
    assert "Python" in body["draft"] and "CLIMAVERSE" in body["draft"]
    assert body["base_version"] is None and "approve" in body["note"]


def test_resume_approve_versioning_and_diff(client, auth):
    draft = client.post("/api/resume/draft", headers=auth,
                        json={"jd_text": SAMPLE_JD, "target_label": "Backend"}).json()
    v1 = client.post("/api/resume/approve", headers=auth, json={
        "content": draft["draft"], "target_label": "Backend"}).json()
    assert v1["version"] == 1 and v1["parent_version"] is None
    client.post("/api/twin/facts", headers=auth, json={
        "entity": "project", "value": "NEXUS: decision-sealing platform, 146 passing tests"})
    draft2 = client.post("/api/resume/draft", headers=auth,
                         json={"jd_text": SAMPLE_JD, "target_label": "Backend"}).json()
    assert "+- NEXUS" in draft2["diff"] or "NEXUS" in draft2["diff"]
    v2 = client.post("/api/resume/approve", headers=auth, json={
        "content": draft2["draft"], "target_label": "Backend"}).json()
    assert v2["version"] == 2 and v2["parent_version"] == 1
    versions = client.get("/api/resume/versions", headers=auth).json()
    assert [v["version"] for v in versions] == [2, 1]    # immutable history


# ---------- decision audit + replay ----------

def test_audit_and_deterministic_replay(client, auth):
    decisions = client.get("/api/audit", headers=auth).json()
    assert decisions
    did = decisions[0]["id"]
    detail = client.get(f"/api/audit/{did}", headers=auth).json()
    assert detail["evidence"] and detail["engine_version"].startswith("rule-engine")
    replayed = client.post(f"/api/audit/{did}/replay", headers=auth).json()
    assert replayed["reproducible"] is True
    assert replayed["twin_changed_since"] is True        # we added facts after deciding
    assert replayed["reasoning_path"]["evidence_used"]
    assert (replayed["recomputed"]["alignment_score"]
            == replayed["original_output"]["alignment_score"])


# ---------- graceful degradation (kill switch) ----------

def test_kill_switch_degrades_gracefully(client, auth, admin_auth):
    assert client.post("/api/admin/llm-kill-switch", headers=admin_auth,
                       json={"llm_down": True}).json()["simulate_llm_down"] is True
    r = client.post("/api/decisions/gap-analysis", headers=auth,
                    json={"jd_text": SAMPLE_JD, "target_label": "Backend"})
    assert r.status_code == 200 and r.json()["fallback_used"] is True
    health = client.get("/api/health/mission").json()
    assert "simulated_down" in health["components"]["llm_adapter"]
    assert health["fallback_counters"].get("llm_fallbacks", 0) >= 1
    client.post("/api/admin/llm-kill-switch", headers=admin_auth, json={"llm_down": False})


def test_health_and_observability_headers(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert "X-Trace-Id" in r.headers and "X-Response-Time-Ms" in r.headers
