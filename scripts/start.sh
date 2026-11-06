#!/bin/sh
# Run with: sh scripts/start.sh [--gpu]
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
docker info >/dev/null
if [ ! -f .env ]; then
    project_name=$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')
    existing=$(docker volume ls --filter "label=com.docker.compose.project=$project_name" --format '{{.Name}}')
    if [ -n "$existing" ]; then
        echo 'Existing DB volume found. Restore the original .env before starting.' >&2
        exit 1
    fi
    password=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
    (umask 077; printf 'POSTGRES_PASSWORD=%s\nDB_PASSWORD=%s\nDB_NAME=ai_sales\nDB_USER=ai_user\n' "$password" "$password" > .env)
fi
case "${1:-}" in
    '') set -- ;;
    --gpu) set -- -f deploy/compose.gpu.yaml ;;
    *) echo 'Usage: sh scripts/start.sh [--gpu]' >&2; exit 1 ;;
esac
docker compose -f compose.yaml -f deploy/compose.backend.yaml -f deploy/compose.portable.yaml "$@" config --quiet
docker compose -f compose.yaml -f deploy/compose.backend.yaml -f deploy/compose.portable.yaml "$@" up -d --build web app
printf '\nCustomer: http://localhost:8080\nAdmin: http://localhost:8501\nAPI: http://localhost:8000/docs\n'
