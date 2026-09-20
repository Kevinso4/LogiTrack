#!/bin/sh
set -e

echo "[fleet-service] aplicando migraciones..."
alembic upgrade head

echo "[fleet-service] arrancando API en :8001"
exec uvicorn app.main:app --host 0.0.0.0 --port 8001 --proxy-headers --no-access-log
