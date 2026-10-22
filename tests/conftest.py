import os

import pytest

os.environ["DATABASE_URL"] = "sqlite://"  # in-memory, isolated from dev db
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["AUTH_RATE_LIMIT_PER_MINUTE"] = "100000"  # relaxed; a dedicated test lowers it
os.environ.setdefault("MAX_UPLOAD_BYTES", "4096")  # small cap so upload tests stay light

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import database  # noqa: E402

# Rebind to a StaticPool in-memory engine so all sessions share one database.
database.engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                                poolclass=StaticPool, future=True)
database.SessionLocal = sessionmaker(bind=database.engine, autoflush=False,
                                     autocommit=False, future=True)

from app.database import Base  # noqa: E402
from app.main import app  # noqa: E402

Base.metadata.create_all(bind=database.engine)

SAMPLE_RESUME = """Alex Example
alex@example.com
Built a Redis-backed pipeline and reduced processing latency by 40%
Also comfortable with kafka event streaming in side experiments.

SKILLS
Python, FastAPI, Docker, Machine Learning, Git

PROJECTS
- CLIMAVERSE: ConvLSTM climate forecasting service with FastAPI endpoints
- CropDoctor: IVR-based crop disease advisory for rural farmers

EXPERIENCE
- Team lead, regional AI Summit hackathon winning team

EDUCATION
- Integrated B.Tech + M.Tech (IT), Example Institute of Technology

CERTIFICATIONS
- Oracle OCI AI Foundations Associate
- Kubernetes fundamentals certificate
"""

SAMPLE_JD = """Backend Engineer (Cloud)
We need strong Python and FastAPI experience. Docker is required; Docker builds
and Docker deployment are daily work. Kubernetes orchestration is a plus.
Kubernetes experience with production clusters preferred. AWS deployment
(EC2, S3) required. SQL databases. Git workflow. CI/CD pipelines.
"""


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def auth(client):
    r = client.post("/api/auth/register", json={
        "email": "micky@example.com", "name": "Micky", "password": "supersecret1",
    })
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def admin_auth(client):
    """A registered user promoted to admin directly in the DB (there is no
    self-serve admin endpoint — privilege is granted out of band)."""
    from sqlalchemy import select

    from app import database
    from app.models import User

    r = client.post("/api/auth/register", json={
        "email": "admin@example.com", "name": "Admin", "password": "supersecret1",
    })
    assert r.status_code == 201
    with database.SessionLocal() as db:
        user = db.execute(select(User).where(User.email == "admin@example.com")).scalar_one()
        user.is_admin = True
        db.commit()
    return {"Authorization": f"Bearer {r.json()['token']}"}
