"""Evidence Scorecard (Blueprint §5.1).

Deterministic, inspectable scoring. Every cell explains itself: which evidence
items were counted, which rule applied. Product invariant: a certificate alone
never lifts a skill above the Medium band (score capped at 40).
"""

import json
import math
import os

WEIGHTS: dict[str, int] = {
    "github_repo": 30,
    "deployed_artifact": 25,
    "open_source": 20,
    "project": 20,
    "hackathon": 15,
    "manual_verified": 15,
    "blog": 10,
    "certificate": 10,
}
CERTIFICATE_ONLY_CAP = 40
BANDS = ((70, "High"), (40, "Medium"), (0, "Low"))

_HERE = os.path.dirname(os.path.abspath(__file__))
_COMPETENCE_MODEL_PATH = os.path.join(
    os.path.dirname(_HERE), "ml", "artifacts", "competence_model.json"
)


def load_competence_model() -> dict | None:
    if os.path.exists(_COMPETENCE_MODEL_PATH):
        try:
            with open(_COMPETENCE_MODEL_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return None


def get_quality_multiplier(item_type: str, reference: str, rules: dict) -> float:
    if not rules or item_type not in rules:
        return 1.0
    rule = rules[item_type]
    ref_lower = (reference or "").lower()

    if "contains" in rule:
        if rule["contains"] in ref_lower:
            return rule["pass_multiplier"]
        return rule["fail_multiplier"]

    if "starts_with" in rule:
        prefixes = rule["starts_with"]
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        if any(ref_lower.startswith(p.lower()) for p in prefixes):
            return rule["pass_multiplier"]
        return rule["fail_multiplier"]

    if "min_length" in rule:
        if len(reference or "") >= rule["min_length"]:
            return rule["pass_multiplier"]
        return rule["fail_multiplier"]

    return 1.0


def band_for_with_model(score: int, bands: list) -> str:
    for threshold, name in bands:
        if score >= threshold:
            return name
    return "Low"


def band_for(score: int) -> str:
    for threshold, name in BANDS:
        if score >= threshold:
            return name
    return "Low"


def score_skill(evidence: list[dict]) -> dict:
    model = load_competence_model()

    if model:
        weights = model["weights"]
        cap = model["certificate_only_cap"]
        bands = model["bands"]
        prior_mean = model["prior_mean"]
        prior_var = model["prior_variance"]
        quality_rules = model["quality_rules"]

        counted, total = [], 0.0
        for item in evidence:
            itype = item.get("type", "")
            base_w = weights.get(itype, 0)
            if base_w:
                mult = get_quality_multiplier(itype, item.get("reference", ""), quality_rules)
                adjusted_weight = base_w * mult
                counted.append({**item, "weight": round(adjusted_weight)})
                total += adjusted_weight

        total = min(total, 100.0)
        rule = "Score = capped sum of verified-evidence weights (Bayesian competence model)."
        types = {c["type"] for c in counted}
        if counted and types == {"certificate"}:
            total = min(total, float(cap))
            rule = (
                "Certificate-only cap applied: certificates alone never raise a skill "
                f"above {cap} (Medium). Add a built artifact to go higher."
            )
        if not counted:
            rule = "No verified evidence yet. Attach a repo, project, or artifact."

        # Bayesian credible interval & uncertainty
        p_mean = float(prior_mean)
        p_var = float(prior_var)

        if total > 0:
            post_var = 1.0 / (1.0 / p_var + total / 10000.0)
            post_mean = post_var * (p_mean / p_var + total / 100.0)
        else:
            post_var = p_var
            post_mean = p_mean

        sigma_post = math.sqrt(post_var)
        lower = max(0.0, round(post_mean - 1.96 * sigma_post, 2))
        upper = min(100.0, round(post_mean + 1.96 * sigma_post, 2))

        score_int = round(total)
        return {
            "score": score_int,
            "band": band_for_with_model(score_int, bands),
            "evidence": counted,
            "rule": rule,
            "credible_interval": [lower, upper],
            "uncertainty": round(sigma_post, 2),
        }

    else:
        counted, total = [], 0
        for item in evidence:
            weight = WEIGHTS.get(item.get("type", ""), 0)
            if weight:
                counted.append({**item, "weight": weight})
                total += weight
        total = min(total, 100)
        rule = "Score = capped sum of verified-evidence weights."
        types = {c["type"] for c in counted}
        if counted and types == {"certificate"}:
            total = min(total, CERTIFICATE_ONLY_CAP)
            rule = (
                "Certificate-only cap applied: certificates alone never raise a skill "
                f"above {CERTIFICATE_ONLY_CAP} (Medium). Add a built artifact to go higher."
            )
        if not counted:
            rule = "No verified evidence yet. Attach a repo, project, or artifact."
        return {"score": total, "band": band_for(total), "evidence": counted, "rule": rule}


def scorecard(twin: dict) -> dict:
    """Per accepted skill: score + band + the exact evidence and rule behind it."""
    model = load_competence_model()
    weights = model["weights"] if model else WEIGHTS
    cap = model["certificate_only_cap"] if model else CERTIFICATE_ONLY_CAP

    rows = []
    for fact in twin["accepted"].get("skill", []):
        scored = score_skill(fact.get("evidence", []))
        rows.append({"skill": fact["value"], **scored})
    rows.sort(key=lambda r: (-r["score"], r["skill"]))
    return {
        "rows": rows,
        "weights": weights,
        "invariant": f"Certificates alone are capped at {cap}/100.",
        "twin_hash": twin["twin_hash"],
    }
