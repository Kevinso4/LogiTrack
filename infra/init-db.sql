-- Database per Service: una base por microservicio, nadie lee la del otro.
-- Se ejecuta una sola vez, cuando el volumen de PostgreSQL está vacío.
CREATE DATABASE fleet_db OWNER logitrack;
CREATE DATABASE tracking_db OWNER logitrack;
CREATE DATABASE routing_db OWNER logitrack;
CREATE DATABASE shipment_db OWNER logitrack;

-- La extensión de TimescaleDB se activa dentro de tracking_db desde la
-- migración de Alembic (0001_tracking), junto con la hypertable.
