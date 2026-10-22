# ── Stage 1: Builder ──────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
ENV PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Production ──────────────────────────────────────────────
FROM python:3.12-slim AS production

WORKDIR /srv/cdis
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Default to production inside the container
    APP_ENV=production

# Install only the pre-built packages from the builder stage.
COPY --from=builder /install /usr/local

# Copy application code and gunicorn config.
COPY app ./app
COPY gunicorn.conf.py .

# Alembic migrations (if present).
COPY alembic.ini ./
COPY alembic/ ./alembic/

# Non-root user for security.
RUN useradd --create-home --shell /bin/bash cdis && chown -R cdis:cdis /srv/cdis
USER cdis

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/livez')" || exit 1

# Gunicorn with UvicornWorker: proper signal handling, pre-fork, graceful shutdown.
CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
