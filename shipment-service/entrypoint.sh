#!/bin/sh
set -e

echo "[shipment-service] esperando a la base de datos..."
INTENTOS=0
until python -c "
import os, socket
from urllib.parse import urlparse
url = urlparse(os.environ['DATABASE_URL'])
socket.create_connection((url.hostname, url.port or 5432), timeout=2)
" 2>/dev/null; do
    INTENTOS=$((INTENTOS + 1))
    if [ "$INTENTOS" -ge 30 ]; then
        echo "base inalcanzable tras 30 intentos"
        exit 1
    fi
    sleep 2
done

echo "[shipment-service] aplicando migraciones..."
INTENTOS=0
until alembic upgrade head; do
    INTENTOS=$((INTENTOS + 1))
    if [ "$INTENTOS" -ge 5 ]; then
        echo "migraciones fallidas"
        exit 1
    fi
    sleep 3
done

echo "[shipment-service] arrancando API en :8004"
exec uvicorn app.main:app --host 0.0.0.0 --port 8004 --proxy-headers --no-access-log
