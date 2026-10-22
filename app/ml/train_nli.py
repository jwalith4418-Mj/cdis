import json
import os


def train_nli():
    # Paths
    here = os.path.dirname(os.path.abspath(__file__))
    artifacts_dir = os.path.join(here, "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)

    # Mock/Rule-based NLI rules
    # E.g. forbidden phrases or checking if the rephrased content matches numbers.
    nli_guard = {
        "model_name": "rule-based-nli-guard-v1",
        "description": "Verifies that no numerical or factual deviation exists in LLM rephrasing.",
        "allowed_leeway_ratio": 1.1,
        "max_words_diff": 50,
        "forbidden_phrases": [
            "guarantee", "assured", "shoo-in", "odds", "chances", "probability",
            "likelihood", "unlikely", "almost certain", "certainly"
        ]
    }

    output_path = os.path.join(artifacts_dir, "nli_guard.json")
    with open(output_path, "w") as f:
        json.dump(nli_guard, f, indent=2)
    print(f"Saved NLI guard to {output_path}")

if __name__ == "__main__":
    train_nli()
