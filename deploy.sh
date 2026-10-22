#!/usr/bin/env bash
# ── CDIS Production Deployment Script ─────────────────────────────────
# One-command deployment: ./deploy.sh
#
# Prerequisites: docker, docker compose v2
# Usage:
#   chmod +x deploy.sh
#   cp .env.production .env   # then edit .env with real secrets
#   ./deploy.sh
set -euo pipefail

COMPOSE_FILE="docker-compose.prod.yml"
PROJECT_NAME="cdis"

# ── Colors ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Pre-flight checks ────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    error "Docker is not installed."; exit 1
fi

if ! docker compose version &>/dev/null; then
    error "Docker Compose v2 is required."; exit 1
fi

if [ ! -f ".env" ]; then
    if [ -f ".env.production" ]; then
        warn ".env not found — copying .env.production → .env"
        cp .env.production .env
        warn "EDIT .env WITH REAL SECRETS before continuing!"
        exit 1
    else
        error "No .env or .env.production found. Create one from the template."; exit 1
    fi
fi

# Validate critical secrets are not placeholder values.
source .env 2>/dev/null || true
if [[ "${JWT_SECRET:-}" == "CHANGE_ME_REQUIRED" || -z "${JWT_SECRET:-}" ]]; then
    error "JWT_SECRET in .env is not set. Generate with: python -c \"import secrets;print(secrets.token_hex(32))\""; exit 1
fi
if [[ "${POSTGRES_PASSWORD:-}" == "CHANGE_ME_REQUIRED" || -z "${POSTGRES_PASSWORD:-}" ]]; then
    error "POSTGRES_PASSWORD in .env is not set."; exit 1
fi

info "Starting CDIS production deployment..."

# ── Build ─────────────────────────────────────────────────────────────
info "Building images..."
docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" build --no-cache

# ── Deploy ────────────────────────────────────────────────────────────
info "Starting services..."
docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" up -d

# ── Wait for health ──────────────────────────────────────────────────
info "Waiting for services to become healthy..."
MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    HEALTHY=$(docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" ps --format json 2>/dev/null | \
              grep -c '"healthy"' || true)
    TOTAL=$(docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" ps --format json 2>/dev/null | \
            wc -l || true)
    if [ "$HEALTHY" -ge 3 ] 2>/dev/null; then
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    echo -n "."
done
echo ""

# ── Status ────────────────────────────────────────────────────────────
info "Service status:"
docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" ps

PUBLIC_PORT=$(grep -E '^PUBLIC_PORT=' .env 2>/dev/null | cut -d= -f2 || echo "80")
PUBLIC_PORT=${PUBLIC_PORT:-80}

echo ""
info "CDIS is running at http://localhost:${PUBLIC_PORT}"
info "API docs (if enabled): http://localhost:${PUBLIC_PORT}/api/docs"
echo ""
info "Useful commands:"
echo "  Logs:    docker compose -f $COMPOSE_FILE -p $PROJECT_NAME logs -f"
echo "  Stop:    docker compose -f $COMPOSE_FILE -p $PROJECT_NAME down"
echo "  Restart: docker compose -f $COMPOSE_FILE -p $PROJECT_NAME restart"
echo "  Shell:   docker compose -f $COMPOSE_FILE -p $PROJECT_NAME exec api bash"
