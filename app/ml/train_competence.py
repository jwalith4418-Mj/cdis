import json
import os

from app.database import SessionLocal
from app.models import User
from app.services.twin import project


def train_competence():
    # Paths
    here = os.path.dirname(os.path.abspath(__file__))
    artifacts_dir = os.path.join(here, "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)

    # Base weights
    base_weights = {
        "github_repo": 30,
        "deployed_artifact": 25,
        "open_source": 20,
        "project": 20,
        "hackathon": 15,
        "manual_verified": 15,
        "blog": 10,
        "certificate": 10,
    }

    # Quality Rules
    quality_rules = {
        "github_repo": {"contains": "github.com", "pass_multiplier": 1.0, "fail_multiplier": 0.8},
        "deployed_artifact": {
            "starts_with": ["http://", "https://"],
            "pass_multiplier": 1.0,
            "fail_multiplier": 0.8,
        },
        "project": {"min_length": 10, "pass_multiplier": 1.0, "fail_multiplier": 0.7},
        "open_source": {"min_length": 10, "pass_multiplier": 1.0, "fail_multiplier": 0.7},
    }

    # Default prior
    prior_mean = 20.0
    prior_variance = 400.0

    # Empirical Bayes: calculate prior from database
    db = SessionLocal()
    try:
        users = db.query(User).all()
        scores = []
        for user in users:
            try:
                twin = project(db, user.id)
                for skill_fact in twin["accepted"].get("skill", []):
                    # Reconstruct the default score logic
                    total = 0
                    evidence = skill_fact.get("evidence", [])
                    has_only_cert = len(evidence) > 0 and all(
                        e.get("type") == "certificate" for e in evidence
                    )

                    for item in evidence:
                        w = base_weights.get(item.get("type", ""), 0)
                        total += w
                    total = min(total, 100)
                    if has_only_cert:
                        total = min(total, 40)
                    scores.append(total)
            except Exception as e:
                print(f"Error projecting twin for user {user.id}: {e}")

        if scores:
            mean = sum(scores) / len(scores)
            var = sum((x - mean) ** 2 for x in scores) / len(scores)
            # Ensure variance is not too small
            var = max(var, 25.0)

            prior_mean = round(mean, 2)
            prior_variance = round(var, 2)
            print(
                f"Fitted Empirical Bayes prior: mean={prior_mean}, variance={prior_variance} "
                f"based on {len(scores)} user-skill instances."
            )
        else:
            print("No skill instances found in DB. Using default prior.")
    except Exception as e:
        print(f"Error connecting to DB: {e}. Using default prior.")
    finally:
        db.close()

    model_params = {
        "weights": base_weights,
        "certificate_only_cap": 40,
        "bands": [[70, "High"], [40, "Medium"], [0, "Low"]],
        "prior_mean": prior_mean,
        "prior_variance": prior_variance,
        "quality_rules": quality_rules,
    }

    output_path = os.path.join(artifacts_dir, "competence_model.json")
    with open(output_path, "w") as f:
        json.dump(model_params, f, indent=2)
    print(f"Saved competence model to {output_path}")


if __name__ == "__main__":
    train_competence()
