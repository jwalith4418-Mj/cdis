"""Resume ingestion: multi-stage parser chain with per-field extraction confidence.

Blueprint §7.1: Parser A (structured sections) → Parser B (lexicon heuristics)
→ manual input (terminal fallback, exposed via POST /api/twin/facts).

Every extracted fact carries an extraction confidence that drives the HITL
tiers (§6): ≥0.8 auto-accepted, 0.6–0.8 pending user confirmation,
<0.6 manual verification required. Facts below 0.8 never enter reasoning
until a human confirms them.
"""
import re
from dataclasses import dataclass, field

# Curated skill lexicon: canonical name -> aliases (lowercase). Deliberately
# explicit and inspectable — no model guesses a skill into existence.
SKILL_LEXICON: dict[str, list[str]] = {
    "Python": ["python"],
    "Java": ["java"],
    "C++": ["c++", "cpp"],
    "JavaScript": ["javascript", "js"],
    "TypeScript": ["typescript"],
    "React": ["react", "react.js", "reactjs"],
    "Node.js": ["node.js", "nodejs", "node"],
    "FastAPI": ["fastapi"],
    "Django": ["django"],
    "Flask": ["flask"],
    "SQL": ["sql", "postgresql", "postgres", "mysql", "sqlite"],
    "NoSQL": ["mongodb", "dynamodb", "nosql", "cassandra"],
    "Redis": ["redis"],
    "Docker": ["docker", "containerization", "containers"],
    "Kubernetes": ["kubernetes", "k8s"],
    "AWS": ["aws", "amazon web services", "ec2", "s3", "lambda"],
    "GCP": ["gcp", "google cloud"],
    "Azure": ["azure"],
    "CI/CD": ["ci/cd", "cicd", "github actions", "jenkins"],
    "Git": ["git", "github", "gitlab"],
    "Linux": ["linux", "ubuntu", "bash", "shell scripting"],
    "Machine Learning": ["machine learning", "ml", "scikit-learn", "sklearn"],
    "Deep Learning": ["deep learning", "pytorch", "tensorflow", "keras", "cnn", "convlstm"],
    "NLP": ["nlp", "natural language processing"],
    "LLMs": ["llm", "llms", "large language model", "prompt engineering", "claude", "gpt"],
    "RAG": ["rag", "retrieval augmented", "retrieval-augmented"],
    "Vector Databases": ["vector database", "pgvector", "pinecone", "faiss", "embeddings"],
    "GraphQL": ["graphql"],
    "REST APIs": ["rest api", "rest apis", "restful"],
    "Microservices": ["microservices", "microservice"],
    "System Design": ["system design", "distributed systems"],
    "Data Structures & Algorithms": ["data structures", "algorithms", "dsa"],
    "Computer Vision": ["computer vision", "opencv", "image processing"],
    "IoT": ["iot", "embedded systems", "arduino", "raspberry pi"],
    "MLOps": ["mlops"],
    "Terraform": ["terraform", "infrastructure as code", "cdk"],
    "Kafka": ["kafka", "event streaming"],
    "Celery": ["celery", "task queue"],
    "WebSockets": ["websocket", "websockets"],
    "HTML/CSS": ["html", "css", "tailwind"],
}

_SECTION_RE = re.compile(
    r"^\s*(technical skills|skills|core competencies|experience|work experience|"
    r"projects|education|certifications|certificates|achievements)\s*:?\s*$",
    re.IGNORECASE,
)
_IMPACT_RE = re.compile(r"\b(\d{1,3})\s*%")


@dataclass
class ExtractedFact:
    entity: str          # skill | project | experience | education | certification | impact_claim
    value: str
    confidence: float
    source_stage: str    # parser_a | parser_b
    detail: str = ""


@dataclass
class ParseResult:
    facts: list[ExtractedFact] = field(default_factory=list)
    stages_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "preamble"
    for raw in text.splitlines():
        line = raw.strip()
        m = _SECTION_RE.match(line)
        if m:
            name = m.group(1).lower()
            if name in ("technical skills", "core competencies"):
                name = "skills"
            if name in ("work experience",):
                name = "experience"
            if name in ("certificates",):
                name = "certifications"
            current = name
            sections.setdefault(current, [])
        elif line:
            sections.setdefault(current, []).append(line)
    return sections


# Compile each alias's boundary-aware pattern once at import instead of rebuilding
# and re-escaping ~80 patterns on every call. Grouped by canonical skill; order
# preserved from SKILL_LEXICON. Per-alias matching is retained exactly, so output
# is identical to the naive version — only faster.
_ALIAS_PATTERNS: list[tuple[str, tuple[re.Pattern, ...]]] = [
    (canonical, tuple(re.compile(rf"(?<![\w+#]){re.escape(alias)}(?![\w+#])")
                      for alias in aliases))
    for canonical, aliases in SKILL_LEXICON.items()
]


def match_skills(text: str) -> set[str]:
    """Canonical skills whose alias appears in `text` as a whole token.

    Word-boundary matching (not substring) — 'git' must not match 'digital'.
    Shared by the parser, the JD requirement extractor, and certificate
    evidence linking so all three agree on what counts as a mention.
    """
    lowered = text.lower()
    return {canonical for canonical, pats in _ALIAS_PATTERNS
            if any(p.search(lowered) for p in pats)}


def extract_jd_requirements(jd_text: str) -> dict[str, int]:
    """Skill -> mention count in a job description (lexicon-based, inspectable).

    Lives beside the lexicon it uses, so the Decision, Resume, and Audit engines
    all depend on the parser for JD parsing rather than on one another.
    """
    lowered = jd_text.lower()
    requirements: dict[str, int] = {}
    for canonical, pats in _ALIAS_PATTERNS:  # one pass, no redundant match_skills call
        count = sum(len(p.findall(lowered)) for p in pats)
        if count:
            requirements[canonical] = count
    return requirements


def parse_resume(text: str) -> ParseResult:
    result = ParseResult()
    text = (text or "").strip()
    if not text:
        result.warnings.append(
            "No readable text found. Use the manual fact builder to enter your profile."
        )
        return result

    sections = _split_sections(text)
    seen_skills: set[str] = set()

    # --- Parser A: structured sections (high confidence) ---
    if "skills" in sections:
        result.stages_used.append("parser_a")
        for skill in sorted(match_skills("\n".join(sections["skills"]))):
            seen_skills.add(skill)
            result.facts.append(ExtractedFact("skill", skill, 0.90, "parser_a",
                                              "Listed in your skills section."))
    for entity, key, conf in (("project", "projects", 0.85), ("experience", "experience", 0.85),
                              ("education", "education", 0.85)):
        for line in sections.get(key, []):
            if _IMPACT_RE.search(line):
                continue  # quantified claims never enter as section facts (HITL only)
            if "parser_a" not in result.stages_used:
                result.stages_used.append("parser_a")
            cleaned = line.lstrip("-•* ").strip()
            if len(cleaned) > 3:
                result.facts.append(ExtractedFact(entity, cleaned, conf, "parser_a",
                                                  f"Found in your {key} section."))
    for line in sections.get("certifications", []):
        if _IMPACT_RE.search(line):
            continue
        cleaned = line.lstrip("-•* ").strip()
        if len(cleaned) > 3:
            result.facts.append(ExtractedFact("certification", cleaned, 0.90, "parser_a",
                                              "Found in your certifications section."))

    # --- Parser B: lexicon scan over full text (medium confidence -> user confirms) ---
    remaining = match_skills(text) - seen_skills
    if remaining:
        result.stages_used.append("parser_b")
        for skill in sorted(remaining):
            result.facts.append(ExtractedFact(
                "skill", skill, 0.65, "parser_b",
                "Mentioned in your resume body but not in a skills section — confirm it.",
            ))

    # --- Quantified impact claims: always low confidence -> manual verification ---
    for raw in text.splitlines():
        if _IMPACT_RE.search(raw) and len(raw.strip()) > 8:
            result.facts.append(ExtractedFact(
                "impact_claim", raw.strip().lstrip("-•* "), 0.50,
                result.stages_used[-1] if result.stages_used else "parser_b",
                "Quantified claims need your verification before they are used anywhere.",
            ))

    if not result.facts:
        result.warnings.append(
            "Nothing could be extracted automatically. Add facts manually — the mission continues."
        )
    return result
