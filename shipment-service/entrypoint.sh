#!/bin/sh
set -e

echo "[shipment-service] aplicando migraciones..."
alembic upgrade head

echo "[shipment-service] arrancando API en :8004"
exec uvicorn app.main:app --host 0.0.0.0 --port 8004 --proxy-headers --no-access-log