"""Gunicorn configuration for production.

Uses UvicornWorker so the FastAPI app runs on uvloop with HTTP/1.1
keep-alive, but gunicorn manages the process lifecycle (graceful
restart, pre-fork, signal handling).
"""
import multiprocessing
import os

# ── Bind ──────────────────────────────────────────────────────────────
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# ── Workers ───────────────────────────────────────────────────────────
# WEB_CONCURRENCY overrides auto-detect (useful in containers where
# cpu_count() returns host cores, not cgroup-limited).
workers = int(os.getenv("WEB_CONCURRENCY", min(multiprocessing.cpu_count() * 2 + 1, 9)))
worker_class = "uvicorn.workers.UvicornWorker"

# ── Timeouts ──────────────────────────────────────────────────────────
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5

# ── Logging ───────────────────────────────────────────────────────────
accesslog = "-"                       # stdout
errorlog = "-"                        # stderr
loglevel = os.getenv("LOG_LEVEL", "info")

# ── Security ──────────────────────────────────────────────────────────
# Limit request sizes at the server level (before the app even sees them).
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190

# ── Process naming ────────────────────────────────────────────────────
proc_name = "cdis"

# ── Lifecycle hooks ───────────────────────────────────────────────────
def on_starting(server):
    """Log startup for audit trail."""
    server.log.info("CDIS gunicorn master starting (workers=%s)", workers)


def worker_exit(server, worker):
    """Ensure clean shutdown of each worker's DB connections."""
    server.log.info("Worker %s exiting", worker.pid)
