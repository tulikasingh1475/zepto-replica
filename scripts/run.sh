#!/usr/bin/env bash
# usage: scripts/run.sh store 8001
set -euo pipefail
cd "$(dirname "$0")/../services/$1"
set -a; source ../../.env; set +a
exec uvicorn app.main:app --reload --port "$2"
