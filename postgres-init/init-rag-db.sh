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
EOSQL
