"""Request schemas. Responses are built explicitly in routers/services so the
API contract stays visible (and so no hiring-probability field can ever leak in)."""
from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ResumeTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)


class ManualFactIn(BaseModel):
    entity: str = Field(pattern="^(skill|project|experience|education|certification)$")
    value: str = Field(min_length=2, max_length=500)


class EvidenceIn(BaseModel):
    skill: str = Field(min_length=1, max_length=120)
    type: str = Field(pattern=("^(github_repo|deployed_artifact|open_source|project"
                               "|hackathon|manual_verified|blog|certificate)$"))
    reference: str = Field(min_length=3, max_length=500)


class GapAnalysisIn(BaseModel):
    jd_text: str = Field(min_length=30, max_length=100_000)
    target_label: str = Field(default="Target role", max_length=200)


class ResumeDraftIn(BaseModel):
    jd_text: str = Field(default="", max_length=100_000)
    target_label: str = Field(default="master", max_length=200)


class ResumeApproveIn(BaseModel):
    content: str = Field(min_length=10, max_length=200_000)
    target_label: str = Field(default="master", max_length=200)
    decision_id: int | None = None


class KillSwitchIn(BaseModel):
    llm_down: bool


class DeleteAccountIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class ApplicationIn(BaseModel):
    target_role: str = Field(min_length=1, max_length=200)
    decision_id: int | None = None
    status: str = Field(default="applied", pattern="^(applied|interview|offer|rejected)$")


class ApplicationStatusIn(BaseModel):
    status: str = Field(pattern="^(applied|interview|offer|rejected)$")


class GithubIn(BaseModel):
    username: str = Field(min_length=1, max_length=39, pattern="^[A-Za-z0-9-]+$")
