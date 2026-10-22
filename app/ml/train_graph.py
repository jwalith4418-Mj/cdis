import json
import math
import os
import sqlite3

from app.services.parser import SKILL_LEXICON, match_skills


def train_graph():
    # Paths
    here = os.path.dirname(os.path.abspath(__file__))
    artifacts_dir = os.path.join(here, "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)

    # Path to database - typically in the project root
    # Project root is parent of 'app' which is parent of 'ml'
    project_root = os.path.dirname(os.path.dirname(here))
    db_path = os.path.join(project_root, "cdis.db")

    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}. Using empty dataset.")
        docs = []
    else:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Load JDs
        cursor.execute("SELECT inputs FROM decisions")
        jds = []
        for row in cursor.fetchall():
            try:
                inputs = json.loads(row[0])
                if "jd_text" in inputs:
                    jds.append(inputs["jd_text"])
            except Exception:
                pass

        # Load Resumes
        cursor.execute("SELECT content FROM resume_versions")
        resumes = [row[0] for row in cursor.fetchall() if row[0]]

        conn.close()
        docs = jds + resumes
        print(
            f"Loaded {len(jds)} JDs and {len(resumes)} Resumes "
            f"for a total of {len(docs)} documents."
        )

    # Extract skills for each document
    doc_skills = []
    skill_counts = {skill: 0 for skill in SKILL_LEXICON}
    co_occurrence_counts = {s1: {s2: 0 for s2 in SKILL_LEXICON} for s1 in SKILL_LEXICON}

    for doc in docs:
        matched = match_skills(doc)
        doc_skills.append(matched)
        for s in matched:
            if s in skill_counts:
                skill_counts[s] += 1

        # Calculate co-occurrences
        matched_list = list(matched)
        for i in range(len(matched_list)):
            s1 = matched_list[i]
            if s1 not in SKILL_LEXICON:
                continue
            for j in range(i, len(matched_list)):
                s2 = matched_list[j]
                if s2 not in SKILL_LEXICON:
                    continue
                co_occurrence_counts[s1][s2] += 1
                if s1 != s2:
                    co_occurrence_counts[s2][s1] += 1

    # Compute transfer matrix (cosine similarity)
    # T[s1][s2] = cos_sim(s1, s2)
    transfer_matrix = {}
    for s1 in SKILL_LEXICON:
        transfer_matrix[s1] = {}
        for s2 in SKILL_LEXICON:
            if s1 == s2:
                transfer_matrix[s1][s2] = 1.0
                continue

            c1 = skill_counts[s1]
            c2 = skill_counts[s2]
            c12 = co_occurrence_counts[s1][s2]

            if c1 > 0 and c2 > 0:
                cos_sim = c12 / math.sqrt(c1 * c2)
            else:
                cos_sim = 0.0

            # Cap transfer credit at 0.5
            transfer_matrix[s1][s2] = min(0.5, cos_sim)

    # Save to JSON
    output_path = os.path.join(artifacts_dir, "skill_transfer.json")
    with open(output_path, "w") as f:
        json.dump(transfer_matrix, f, indent=2)
    print(f"Saved transfer matrix to {output_path}")


if __name__ == "__main__":
    train_graph()
