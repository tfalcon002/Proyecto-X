-- Migración 001: tabla de historial de interacciones del agente.
--
-- Para deployments que ya tenían un volumen de Postgres inicializado antes
-- de este cambio (postgres-init/init-rag-db.sh solo corre en el primer
-- arranque del volumen, vía docker-entrypoint-initdb.d, y no vuelve a
-- ejecutarse). Correr esta migración una sola vez contra la base del RAG
-- (RAG_DB, normalmente "falcon_rag") para agregar la tabla sin reiniciar
-- el contenedor ni tocar datos existentes.
--
-- Requiere que la tabla "clients" ya exista (se crea en el mismo
-- init-rag-db.sh, PR #10 "Add multitenant client_id to RAG service").
--
-- Idempotente: usa IF NOT EXISTS en todo, así que correrla más de una vez
-- no rompe nada.

BEGIN;

CREATE TABLE IF NOT EXISTS agente_interacciones (
    id BIGSERIAL PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients (client_id),
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    from_number TEXT,
    intent TEXT,
    user_message TEXT,
    agent_response TEXT,
    wa_message_id TEXT,
    session_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agente_interacciones_client_id
    ON agente_interacciones (client_id);
CREATE INDEX IF NOT EXISTS idx_agente_interacciones_created_at
    ON agente_interacciones (created_at);

COMMIT;
