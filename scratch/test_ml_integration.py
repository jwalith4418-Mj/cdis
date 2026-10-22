import os
import sys
import shutil
import json
import math
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force fallback settings
os.environ["SIMULATE_LLM_DOWN"] = "1"
os.environ["DATABASE_URL"] = "sqlite://"

from app.database import Base
from app.models import User, TwinEvent
from app.services.evidence import score_skill, load_competence_model
from app.services.decision import compute_alignment, run_gap_analysis
from app.services.twin import add_facts, add_evidence, project
from app.services.parser import ExtractedFact

def run_tests():
    artifacts_dir = os.path.join(PROJECT_ROOT, "app", "ml", "artifacts")
    transfer_path = os.path.join(artifacts_dir, "skill_transfer.json")
    transfer_bak = os.path.join(artifacts_dir, "skill_transfer_bak.json")
    competence_path = os.path.join(artifacts_dir, "competence_model.json")
    competence_bak = os.path.join(artifacts_dir, "competence_model_bak.json")

    # Setup database
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    print("==================================================")
    print("      CDIS INTEGRATION VALIDATION TEST SUITE      ")
    print("==================================================")

    # Setup dummy user
    user = User(
        email="dev@example.com",
        name="Dev User",
        password_hash="hash",
        is_admin=False
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"[DB] Created dummy user: {user.name} (ID: {user.id})")

    # Add facts to user's twin
    facts = [
        ExtractedFact(entity="skill", value="FastAPI", confidence=0.9, source_stage="resume", detail=""),
    ]
    add_facts(db, user.id, facts)
    add_evidence(db, user.id, "FastAPI", "github_repo", "https://github.com/dev/my-fastapi-app")
    print("[Twin] Added skill FastAPI with Github Repo evidence.")

    twin = project(db, user.id)
    print(f"[Twin] Projected twin: {json.dumps(twin, indent=2)}")

    print("\n--------------------------------------------------")
    print("TEST 1: SKILL TRANSFER MATRIX & CREDIT CALCULATION")
    print("--------------------------------------------------")
    # JD requires "Python" (1 mention). User has FastAPI (score 100 via github repo).
    # Co-occurrence transfer from Python -> FastAPI is 0.5.
    requirements = {"Python": 1}
    coverage = {"FastAPI": 100}

    # 1. With transfer matrix active
    assert os.path.exists(transfer_path), "skill_transfer.json is missing!"
    res_matrix_active = compute_alignment(requirements, coverage)
    print(f"Transfer Matrix Active Alignment Output:")
    print(json.dumps(res_matrix_active, indent=2))
    
    # Assert alignment score is 50 because transfer matrix factor Python->FastAPI is 0.5
    alignment_score_active = res_matrix_active["alignment_score"]
    assert alignment_score_active == 50, f"Expected alignment score of 50, got {alignment_score_active}"
    print(f"OK - Active Transfer Matrix: correctly applied partial credit! (Score: {alignment_score_active}%)")

    print("\n--------------------------------------------------")
    print("TEST 2: LATENT COMPETENCE MODEL STATISTICS")
    print("--------------------------------------------------")
    # Retrieve evidence score for FastAPI.
    # FastAPI has github_repo evidence.
    evidence_items = twin["accepted"]["skill"][0]["evidence"]
    assert os.path.exists(competence_path), "competence_model.json is missing!"
    
    res_comp_active = score_skill(evidence_items)
    print(f"Competence Model Active Output:")
    print(json.dumps(res_comp_active, indent=2))
    
    assert "credible_interval" in res_comp_active, "Credible interval is missing!"
    assert "uncertainty" in res_comp_active, "Uncertainty is missing!"
    print("OK - Active Competence Model: correctly calculated credible intervals and uncertainty!")

    print("\n--------------------------------------------------")
    print("TEST 3: FALLBACK PATHS (ARTIFACT REMOVAL)")
    print("--------------------------------------------------")
    # Move files to test fallbacks
    print("[System] Temporarily renaming artifacts to test fallback behavior...")
    shutil.move(transfer_path, transfer_bak)
    shutil.move(competence_path, competence_bak)

    try:
        # 1. Test transfer matrix fallback
        res_matrix_fallback = compute_alignment(requirements, coverage)
        print(f"Transfer Matrix Fallback Alignment Output:")
        print(json.dumps(res_matrix_fallback, indent=2))
        alignment_score_fallback = res_matrix_fallback["alignment_score"]
        assert alignment_score_fallback == 0, f"Expected fallback alignment score of 0, got {alignment_score_fallback}"
        print("OK - Transfer Matrix Fallback: correctly fell back to 0% (no transfer credit applied).")

        # 2. Test competence model fallback
        res_comp_fallback = score_skill(evidence_items)
        print(f"Competence Model Fallback Output:")
        print(json.dumps(res_comp_fallback, indent=2))
        assert "credible_interval" not in res_comp_fallback, "Credible interval should not exist in fallback!"
        assert "uncertainty" not in res_comp_fallback, "Uncertainty should not exist in fallback!"
        print("OK - Competence Model Fallback: correctly fell back to rule-based weights with no Bayesian stats.")

        # 3. Test full gap analysis under fallback
        print("[Gap Analysis] Running full gap analysis under fallback...")
        jd_text = "Looking for a Python Developer who knows Python."
        gap_res_fallback = run_gap_analysis(db, user.id, twin, jd_text, "Python Developer")
        print(f"Gap Analysis Fallback Output:")
        print(json.dumps(gap_res_fallback, indent=2))
        print("OK - Full Gap Analysis Fallback: completed successfully with no exceptions.")

    finally:
        # Restore files
        print("[System] Restoring artifacts...")
        shutil.move(transfer_bak, transfer_path)
        shutil.move(competence_bak, competence_path)

    # 4. Test full gap analysis with active models
    print("\n[Gap Analysis] Running full gap analysis with active models...")
    gap_res_active = run_gap_analysis(db, user.id, twin, jd_text, "Python Developer")
    print(f"Gap Analysis Active Output:")
    print(json.dumps(gap_res_active, indent=2))
    assert gap_res_active["alignment_score"] == 15, f"Expected 15% alignment, got {gap_res_active['alignment_score']}%"
    print("OK - Full Gap Analysis Active: completed successfully with active models and transfer credit!")

    print("\n==================================================")
    print("         ALL ML INTEGRATION TESTS PASSED!          ")
    print("==================================================")
    db.close()

if __name__ == "__main__":
    run_tests()
