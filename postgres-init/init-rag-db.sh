#!/bin/bash
# Se ejecuta una sola vez, en el primer arranque del volumen de postgres
# (docker-entrypoint-initdb.d). Crea una base de datos separada para el
# RAG y habilita en ella la extensión pgvector.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE "${RAG_DB}";
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${RAG_DB}" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;

    -- Registro de clientes de Falcon (arquitectura multitenant): cada
    -- documento ingestado y cada consulta al RAG queda asociado a un
    -- client_id que debe existir acá. Ver rag-service/main.py.
    CREATE TABLE IF NOT EXISTS clients (
        client_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- Historial de interacciones del agente (WhatsApp y futuros canales):
    -- un registro por cada mensaje de usuario respondido, con la
    -- intención detectada y la respuesta final enviada. Alimentado por
    -- POST /interactions (ver rag-service/main.py), llamado desde el nodo
    -- "Log Interaction" del workflow de n8n.
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
EOSQL
