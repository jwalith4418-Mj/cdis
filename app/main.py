"""CDIS API. Serves the JSON API under /api and the SPA at /."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import settings
from .database import Base, engine
from .observability import ObservabilityMiddleware, logger, trace_id_var
from .routers import account, audit, auth, decisions, outcomes, resume, twin

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup env=%s db=%s", settings.app_env,
                settings.database_url.split("://", 1)[0])
    yield
    from .services import decision
    if decision._client is not None:
        decision._client.close()


app = FastAPI(
    title=settings.app_name, version=settings.version, lifespan=lifespan,
    # Interactive docs + schema expose the full API surface — disabled in production.
    docs_url="/api/docs" if settings.enable_docs else None,
    openapi_url="/api/openapi.json" if settings.enable_docs else None,
)
app.add_middleware(ObservabilityMiddleware)

# CORS — configured via CORS_ORIGINS env var (comma-separated).
# No-op when the list is empty (production default blocks cross-origin).
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
for router in (auth.router, twin.router, decisions.router, resume.router,
               audit.router, account.router, outcomes.router):
    app.include_router(router)


def _error(status_code: int, detail, trace_id: str) -> JSONResponse:
    return JSONResponse({"detail": detail, "trace_id": trace_id}, status_code=status_code)


@app.exception_handler(HTTPException)
async def _http_exc(request: Request, exc: HTTPException):
    resp = _error(exc.status_code, exc.detail, trace_id_var.get())
    if exc.headers:
        resp.headers.update(exc.headers)
    return resp


@app.exception_handler(RequestValidationError)
async def _validation_exc(request: Request, exc: RequestValidationError):
    return _error(422, jsonable_encoder(exc.errors()), trace_id_var.get())


@app.exception_handler(Exception)
async def _unhandled_exc(request: Request, exc: Exception):
    trace_id = trace_id_var.get()
    logger.exception("unhandled error", extra={"trace_id": trace_id})
    return _error(500, "Internal error. This has been logged.", trace_id)


_STATIC = Path(__file__).parent / "static"
_INDEX = _STATIC / "index.html"
_LANDING = _STATIC / "landing.html"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(_INDEX)


@app.get("/landing", include_in_schema=False)
def landing():
    """Premium marketing page. Served at /landing so the app stays at / for now;
    swap the two routes to make this the public front door."""
    return FileResponse(_LANDING)
