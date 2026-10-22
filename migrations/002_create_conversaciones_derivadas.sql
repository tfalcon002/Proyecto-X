-- Migración 002: conversaciones derivadas a una persona (pausa del bot).
--
-- El rag-service ya crea esta tabla al arrancar (_ensure_schema en
-- rag-service/main.py), así que normalmente no hace falta correrla a mano.
-- Queda como referencia para deployments que gestionan el esquema aparte.
-- Idempotente.

BEGIN;

CREATE TABLE IF NOT EXISTS conversaciones_derivadas (
    client_id TEXT NOT NULL REFERENCES clients (client_id),
    from_number TEXT NOT NULL,
    reason TEXT,
    summary TEXT,
    paused_until TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, from_number)
);

CREATE INDEX IF NOT EXISTS idx_agente_interacciones_from_number
    ON agente_interacciones (client_id, from_number, created_at);

COMMIT;
