#!/usr/bin/env bash
# usage: scripts/up.sh [profile ...]
set -euo pipefail
cd "$(dirname "$0")/.."
args=(); for p in "$@"; do args+=(--profile "$p"); done
docker compose --env-file .env "${args[@]}" up -d
