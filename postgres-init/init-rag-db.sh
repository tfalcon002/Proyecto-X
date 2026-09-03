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
EOSQL
