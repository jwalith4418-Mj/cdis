import os
import sys
import random
from datetime import datetime, UTC, timedelta

# Force mock LLM behavior to avoid calling Anthropic API and speed up runs
os.environ["SIMULATE_LLM_DOWN"] = "1"

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import engine, SessionLocal
from app.models import User, TwinEvent, Decision, ResumeVersion, Application
from app.security import hash_password
from app.services.parser import parse_resume, extract_jd_requirements
from app.services.twin import add_facts, resolve_fact, add_evidence, project
from app.services.decision import run_gap_analysis
from app.services.resume import approve, generate_draft

# Names for synthetic users
FIRST_NAMES = [
    "Alice", "Bob", "Charlie", "David", "Eva", "Frank", "Grace", "Hannah", "Ivan", "Julia",
    "Kevin", "Liam", "Mia", "Noah", "Olivia", "Penelope", "Quinn", "Ryan", "Sophia", "Thomas",
    "Ursula", "Victor", "Wendy", "Xavier", "Yasmine", "Zachary", "Adam", "Bella", "Connor", "Diana",
    "Ethan", "Fiona", "George", "Harper", "Ian", "Jessica", "Kyle", "Luna", "Mason", "Nora",
    "Oliver", "Paige", "Quentin", "Ruby", "Samuel", "Taylor", "Umar", "Victoria", "Wyatt", "Zoe"
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
    "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
    "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts"
]

# 5 Core career profiles to generate realistic resumes
PROFILES = {
    "Backend": {
        "skills": ["Python", "FastAPI", "Django", "Flask", "SQL", "NoSQL", "Redis", "Git", "Linux", "REST APIs", "Microservices", "System Design", "Data Structures & Algorithms"],
        "experience": [
            "Senior Backend Engineer at TechCorp. Designed high-performance REST APIs in Python using FastAPI, yielding a 25% throughput boost.",
            "Software Developer at DevStudio. Developed REST APIs and maintained SQL databases with Postgres and Redis.",
            "Software Engineer at CloudTech. Designed and migrated monolith architecture to microservices using Node.js and Python.",
            "Backend Developer at NextGen. Optimised database queries, resulting in 30% faster load times.",
            "API Engineer at DataFlow. Developed Celery workers and RabbitMQ event streaming systems."
        ],
        "projects": [
            "High-throughput asynchronous task worker built using Python, FastAPI, and Redis.",
            "Microservices orchestration and deployment using Docker and Git.",
            "Distributed cache store integration with Postgres and Redis database.",
            "API Gateway implementation with JWT authentication and rate limiting."
        ],
        "certifications": [
            "AWS Certified Solutions Architect - Associate",
            "Certified Kubernetes Administrator (CKA)",
            "HashiCorp Certified: Terraform Associate"
        ]
    },
    "Frontend": {
        "skills": ["JavaScript", "TypeScript", "React", "HTML/CSS", "GraphQL", "REST APIs", "Git"],
        "experience": [
            "Frontend Developer at WebLabs. Rebuilt the main dashboard using React and TypeScript, improving load time by 40%.",
            "UI Engineer at PixelPerfect. Designed and styled complex interfaces using React, Tailwind CSS, and HTML/CSS.",
            "Frontend Engineer at DesignSystems. Maintained and published internal React component library.",
            "Software Engineer at InterfaceInc. Developed responsive web applications with TypeScript and GraphQL.",
            "Javascript Developer at AppBuilder. Built complex drag-and-drop workflow interfaces."
        ],
        "projects": [
            "Interactive dashboard project using React and Tailwind CSS.",
            "Migrated large-scale frontend application from JavaScript to TypeScript.",
            "Real-time analytics dashboard powered by WebSockets and React.",
            "Accessible component library compliant with WCAG guidelines."
        ],
        "certifications": [
            "Meta Front-End Developer Professional Certificate",
            "React Certified Professional",
            "UX/UI Design Specialist Certification"
        ]
    },
    "Fullstack": {
        "skills": ["Python", "JavaScript", "TypeScript", "React", "Node.js", "FastAPI", "SQL", "NoSQL", "REST APIs", "GraphQL", "HTML/CSS", "Git"],
        "experience": [
            "Fullstack Engineer at Nexa. Built end-to-end web applications with React on the frontend and Node.js on the backend.",
            "Software Engineer at BizSoft. Designed RESTful endpoints using FastAPI and constructed responsive interfaces in React.",
            "Fullstack Developer at StreamLine. Developed full-stack SaaS platform using Python, React, and PostgreSQL.",
            "Senior Fullstack Developer at SyncTech. Led team of 4 developers building e-commerce applications.",
            "Web Developer at StarterCorp. Maintained legacy PHP and Node.js backends while building new React pages."
        ],
        "projects": [
            "E-commerce platform with Node.js backend, React frontend, and SQL database.",
            "Real-time chat application using WebSockets, Node.js, and React.",
            "Job board portal with search indexing using Vector Databases.",
            "SaaS billing integration system using Stripe, FastAPI, and React."
        ],
        "certifications": [
            "Full Stack Web Development Certification",
            "AWS Certified Developer - Associate",
            "MongoDB Certified Developer"
        ]
    },
    "Data Science / ML": {
        "skills": ["Python", "SQL", "Machine Learning", "Deep Learning", "NLP", "LLMs", "RAG", "Vector Databases", "MLOps", "Computer Vision", "Git"],
        "experience": [
            "Machine Learning Engineer at SmartAI. Trained and deployed deep learning models, increasing inference speed by 50%.",
            "Data Scientist at InsightLab. Designed Retrieval-Augmented Generation (RAG) systems using LLMs and Vector Databases.",
            "AI Engineer at FutureTech. Deployed NLP pipelines for automated document classification.",
            "Research Engineer at VisionSoft. Developed computer vision algorithms for object detection.",
            "Data Scientist at FinanceCo. Built credit scoring machine learning models with 95% accuracy."
        ],
        "projects": [
            "NLP sentiment analysis model deployed on GCP.",
            "Vector DB search optimization reducing search time by 25%.",
            "Custom RAG pipeline with LlamaIndex and pgvector.",
            "MLOps pipeline with MLflow for tracking model parameters and lineage."
        ],
        "certifications": [
            "TensorFlow Developer Certificate",
            "Google Cloud Professional Machine Learning Engineer",
            "DeepLearning.AI TensorFlow Developer"
        ]
    },
    "DevOps / Cloud": {
        "skills": ["Linux", "Docker", "Kubernetes", "AWS", "GCP", "Azure", "CI/CD", "Terraform", "Git", "System Design", "Kafka"],
        "experience": [
            "DevOps Engineer at CloudScale. Configured Kubernetes clusters on AWS and automated CI/CD workflows.",
            "Infrastructure Engineer at OpsLab. Wrote Terraform scripts to deploy highly-available cloud infrastructure.",
            "Site Reliability Engineer at SaaSify. Setup monitoring and alerting with Prometheus, Grafana, and Linux.",
            "Cloud Engineer at GlobalCorp. Migrated on-premise infrastructure to GCP and AWS.",
            "System Administrator at HostInc. Maintained hundreds of Linux servers and automated bash scripting."
        ],
        "projects": [
            "Automated continuous integration and delivery pipelines using Git and GitHub Actions.",
            "Containerized legacy applications using Docker and migrated to Kubernetes.",
            "Infrastructure as Code setup for multi-region active-active deployments.",
            "Log aggregation and monitoring stack using Elasticsearch, Fluentd, and Kibana."
        ],
        "certifications": [
            "Certified Kubernetes Administrator (CKA)",
            "AWS Certified Solutions Architect - Professional",
            "HashiCorp Certified: Terraform Associate"
        ]
    }
}

# 20 Job Descriptions representing a wide range of roles
JOB_DESCRIPTIONS = [
    {
        "title": "Backend Engineer (FastAPI/Python)",
        "description": "We are seeking a Backend Engineer skilled in Python and FastAPI. The ideal candidate will design REST APIs and work with SQL databases (PostgreSQL/MySQL). Experience with Docker, Redis, and Microservices is required."
    },
    {
        "title": "Frontend Engineer (React/TypeScript)",
        "description": "Join us as a Frontend Engineer! You will build responsive interfaces using React, JavaScript, and TypeScript. Experience with HTML/CSS, Tailwind, and GraphQL is highly preferred."
    },
    {
        "title": "DevOps Architect",
        "description": "Looking for a DevOps Architect to manage our cloud infrastructure. Required skills: AWS, Terraform, Docker, and Kubernetes. You will build and maintain CI/CD pipelines using GitHub Actions."
    },
    {
        "title": "MLOps Engineer",
        "description": "We are hiring an MLOps Engineer to bridge the gap between ML models and deployment. You need experience with Python, Machine Learning, Docker, Kubernetes, and MLOps platforms."
    },
    {
        "title": "Data Scientist",
        "description": "Seeking a Data Scientist to analyze complex datasets. Required: Python, SQL, and Machine Learning. Experience with Deep Learning (PyTorch/TensorFlow) and NLP is a plus."
    },
    {
        "title": "Fullstack Developer",
        "description": "We need a Fullstack Developer to work on end-to-end features. You should have experience with TypeScript, React, Node.js, and SQL databases. Familiarity with REST APIs is required."
    },
    {
        "title": "System Architect",
        "description": "Senior role focusing on distributed systems. Required skills: System Design, Microservices, Kafka, Redis, and Python. Experience building high-performance APIs."
    },
    {
        "title": "Cloud Platform Engineer",
        "description": "Responsible for managing cloud platform services. Skills: GCP, Terraform, CI/CD, Kubernetes, and Linux. Git operations are key."
    },
    {
        "title": "Python Developer",
        "description": "We are looking for a Python Developer experienced with Django and Flask. Must know SQL, Git, and how to design clean REST APIs."
    },
    {
        "title": "AI Applications Engineer",
        "description": "Build cutting-edge AI apps with LLMs, RAG, and Vector Databases. Must be fluent in Python, FastAPI, and prompt engineering."
    },
    {
        "title": "Mobile Backend Engineer",
        "description": "Build high-throughput backends for our mobile app. Required: Node.js, GraphQL, NoSQL (MongoDB), Redis, and WebSockets."
    },
    {
        "title": "SRE (Site Reliability Engineer)",
        "description": "Focus on reliability and observability. Required: Linux, Bash scripting, Docker, Kubernetes, AWS, and Prometheus."
    },
    {
        "title": "Data Engineer",
        "description": "Build data pipelines. Required: Python, SQL, Kafka, Celery, and NoSQL databases. Experience with Docker and Linux is necessary."
    },
    {
        "title": "Deep Learning Specialist",
        "description": "R&D team seeking expert in Deep Learning. Experience with PyTorch, TensorFlow, Computer Vision, and NLP. Must know Python."
    },
    {
        "title": "Computer Vision Engineer",
        "description": "Build visual intelligence systems. Required: Computer Vision, Deep Learning, OpenCV, Python, and C++."
    },
    {
        "title": "Fullstack JS Developer",
        "description": "JavaScript/TypeScript focus. Skills: React, Node.js, HTML/CSS, WebSockets, and REST APIs. MongoDB (NoSQL) database."
    },
    {
        "title": "IoT Systems Developer",
        "description": "Embedded developer for IoT products. Required: C++, IoT, Linux, Raspberry Pi, and REST APIs."
    },
    {
        "title": "Solutions Engineer",
        "description": "Customer-facing technical role. Required: JavaScript, HTML/CSS, REST APIs, and SQL. Good system design overview."
    },
    {
        "title": "Lead Software Engineer",
        "description": "Lead a team of engineers. Must have deep knowledge in Python, System Design, Microservices, AWS, and Git."
    },
    {
        "title": "Django Developer",
        "description": "Build complex web apps using Django and PostgreSQL. Required: Django, Python, HTML/CSS, Celery, and Git."
    }
]

# Evidence generators
def get_github_ref(name: str, skill: str) -> str:
    username = name.lower().replace(" ", "")
    repos = [
        f"https://github.com/{username}/{skill.lower().replace(' ', '-')}-service",
        f"https://github.com/{username}/{skill.lower().replace(' ', '-')}-app",
        f"https://github.com/{username}/awesome-{skill.lower().replace(' ', '-')}"
    ]
    return random.choice(repos)

def get_cert_ref(skill: str) -> str:
    certs = [
        f"{skill} Certified Professional",
        f"Advanced {skill} Certification",
        f"Certified {skill} Developer",
        f"Official {skill} Foundation Certificate"
    ]
    return random.choice(certs)

def get_blog_ref(name: str, skill: str) -> str:
    username = name.lower().replace(" ", "")
    blogs = [
        f"https://medium.com/@{username}/mastering-{skill.lower().replace(' ', '-')}",
        f"https://dev.to/{username}/how-i-built-a-project-with-{skill.lower().replace(' ', '-')}",
        f"https://{username}.hashnode.dev/scaling-{skill.lower().replace(' ', '-')}-applications"
    ]
    return random.choice(blogs)

def get_artifact_ref(name: str, skill: str) -> str:
    username = name.lower().replace(" ", "")
    artifacts = [
        f"https://{username}-{skill.lower().replace(' ', '-')}.vercel.app",
        f"https://{username}-{skill.lower().replace(' ', '-')}.onrender.com",
        f"https://{username}-{skill.lower().replace(' ', '-')}.herokuapp.com"
    ]
    return random.choice(artifacts)

def generate_resume_text(name: str, email: str, profile_name: str) -> str:
    profile = PROFILES[profile_name]
    num_skills = min(8, len(profile["skills"]))
    selected_skills = random.sample(profile["skills"], k=random.randint(5, num_skills))
    skills_str = ", ".join(selected_skills)
    
    selected_exp = random.sample(profile["experience"], k=random.randint(1, 2))
    exp_str = "\n".join([f"- {exp}" for exp in selected_exp])
    
    selected_proj = random.sample(profile["projects"], k=random.randint(1, 2))
    proj_str = "\n".join([f"- {proj}" for proj in selected_proj])
    
    selected_cert = random.choice(profile["certifications"])
    
    return f"""{name}
{email}

Technical Skills:
{skills_str}

Work Experience:
{exp_str}

Projects:
{proj_str}

Education:
- BS in Computer Science, State University

Certifications:
- {selected_cert}"""

def main():
    print("Connecting to the database...")
    db: Session = SessionLocal()
    
    try:
        db.query(Application).delete()
        db.query(ResumeVersion).delete()
        db.query(Decision).delete()
        db.query(TwinEvent).delete()
        db.query(User).delete()
        db.commit()
        print("Database wiped successfully.")
    except Exception as e:
        db.rollback()
        print(f"Error during database wipe: {e}")
        
    try:
        db.execute(text("DELETE FROM sqlite_sequence WHERE name IN ('users', 'twin_events', 'decisions', 'resume_versions', 'applications')"))
        db.commit()
        print("Database sequences reset.")
    except Exception as e:
        db.rollback()
        print(f"Warning: sqlite_sequence reset skipped: {e}")
        
    print("Generating pre-hashed password for faster seeding...")
    pwd_hash = hash_password("password123")
    
    print("Generating 50 synthetic users and ingestion logs...")
    users = []
    
    # 50 unique names and emails
    for i in range(50):
        first = FIRST_NAMES[i % len(FIRST_NAMES)]
        last = LAST_NAMES[i % len(LAST_NAMES)]
        name = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        
        # Create User
        user = User(
            name=name,
            email=email,
            password_hash=pwd_hash,
            is_admin=(i == 0) # Make first user admin
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        users.append(user)
        
        # Determine career profile
        profile_name = list(PROFILES.keys())[i % len(PROFILES)]
        resume_text = generate_resume_text(name, email, profile_name)
        
        # Ingest/parse resume facts
        parse_result = parse_resume(resume_text)
        fact_events = add_facts(db, user.id, parse_result.facts)
        
        # Simulate User HITL interaction (confirm/reject facts)
        for ev in fact_events:
            status = ev.payload.get("status")
            if status in ("pending", "manual_review"):
                r = random.random()
                if r < 0.85:
                    resolve_fact(db, user.id, ev.id, "confirmed")
                elif r < 0.95:
                    resolve_fact(db, user.id, ev.id, "rejected")
                    
        # Add random evidence to accepted skills to drive scoring
        twin = project(db, user.id)
        accepted_skills = twin["accepted"].get("skill", [])
        for f in accepted_skills:
            skill = f["value"]
            if random.random() < 0.75:
                # Choose 1 to 3 distinct evidence types
                n_ev = random.randint(1, 3)
                ev_types = random.sample(["github_repo", "deployed_artifact", "certificate", "blog"], n_ev)
                for et in ev_types:
                    if et == "github_repo":
                        ref = get_github_ref(name, skill)
                    elif et == "deployed_artifact":
                        ref = get_artifact_ref(name, skill)
                    elif et == "certificate":
                        ref = get_cert_ref(skill)
                    else:
                        ref = get_blog_ref(name, skill)
                    add_evidence(db, user.id, skill, et, ref)
                    
        # Final projection with evidence attached
        twin = project(db, user.id)
        
        # Initial master resume version approval
        approve(db, user.id, resume_text, "master", None)
        
        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/50 users...")

    print("Running gap-analyses and simulating application outcomes...")
    gap_analysis_count = 0
    application_count = 0
    
    for i, user in enumerate(users):
        twin = project(db, user.id)
        user_skills = {f["value"] for f in twin["accepted"].get("skill", [])}
        
        # Match user to JDs by overlapping skills
        jd_matches = []
        for jd in JOB_DESCRIPTIONS:
            reqs = extract_jd_requirements(jd["description"])
            overlap = len(user_skills.intersection(reqs.keys()))
            jd_matches.append((overlap, jd))
            
        # Sort JDs by overlap descending, pick top 5, and randomly sample 2 or 3 of them
        jd_matches.sort(key=lambda x: x[0], reverse=True)
        top_matches = [m[1] for m in jd_matches[:5]]
        n_analyses = random.randint(2, 3)
        selected_jds = random.sample(top_matches, k=n_analyses)
        
        for jd in selected_jds:
            # Run Gap-Analysis (inserts Decision)
            analysis = run_gap_analysis(db, user.id, twin, jd["description"], jd["title"])
            gap_analysis_count += 1
            
            # Simulate Outcome Funnel Application (applied -> interview -> offer or rejected)
            if random.random() < 0.85: # 85% application rate
                score = analysis["alignment_score"]
                
                # Determine realistic status based on match score
                if score >= 70:
                    status = random.choices(
                        ["applied", "interview", "offer", "rejected"],
                        weights=[10, 30, 45, 15],
                        k=1
                    )[0]
                elif score >= 40:
                    status = random.choices(
                        ["applied", "interview", "offer", "rejected"],
                        weights=[20, 40, 15, 25],
                        k=1
                    )[0]
                else:
                    status = random.choices(
                        ["applied", "interview", "offer", "rejected"],
                        weights=[30, 15, 5, 50],
                        k=1
                    )[0]
                
                # Simulate realistic timestamps within the last month
                created_days_ago = random.randint(5, 30)
                created_at = datetime.now(UTC) - timedelta(days=created_days_ago)
                
                if status == "applied":
                    updated_at = created_at
                else:
                    updated_days_after = random.randint(1, min(4, created_days_ago))
                    updated_at = created_at + timedelta(days=updated_days_after)
                
                # Create Application
                app = Application(
                    user_id=user.id,
                    target_role=jd["title"],
                    decision_id=analysis["decision_id"],
                    status=status,
                    consented=True,
                    created_at=created_at,
                    updated_at=updated_at
                )
                db.add(app)
                db.commit()
                application_count += 1
                
                # Generate and approve tailored ResumeVersion for this role
                tailored_content = generate_draft(twin, user.name, user.email, jd["description"], jd["title"])
                approve(db, user.id, tailored_content, jd["title"], analysis["decision_id"])

        if (i + 1) % 10 == 0:
            print(f"  Completed analyses/funnels for {i + 1}/50 users...")

    print("\nVerification of Row Counts:")
    user_count = db.query(User).count()
    event_count = db.query(TwinEvent).count()
    decision_count = db.query(Decision).count()
    resume_count = db.query(ResumeVersion).count()
    app_count = db.query(Application).count()
    
    print("-" * 40)
    print(f"Users Table:          {user_count} (Expected: 50+)")
    print(f"TwinEvents Table:     {event_count} (Expected: ~1000+ facts, edits, evidence)")
    print(f"Decisions Table:      {decision_count} (Expected: 100+ gap-analyses)")
    print(f"ResumeVersions Table: {resume_count} (Expected: ~150+ master + tailored versions)")
    print(f"Applications Table:   {app_count} (Expected: ~100+ simulated outcomes)")
    print("-" * 40)
    print("Database seeding completed successfully!")
    db.close()

if __name__ == "__main__":
    main()
