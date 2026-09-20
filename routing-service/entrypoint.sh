#!/bin/sh
set -e

echo "[routing-service] aplicando migraciones..."
alembic upgrade head

echo "[routing-service] arrancando API en :8003"
exec uvicorn app.main:app --host 0.0.0.0 --port 8003 --proxy-headers --no-access-log