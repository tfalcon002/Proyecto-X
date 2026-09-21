# Falcon RAG Service (Fase 3 + Etapa 4: multitenant)

Microservicio de ingesta y consulta de documentos, usado internamente por
n8n para responder preguntas con contexto propio (ver
`workflows/whatsapp-rag-inbound.json`, nodo "Query RAG (LlamaIndex)").
Multitenant: todos los clientes de Falcon comparten la misma base y la
misma tabla de documentos, aislados por `client_id`.

## Arquitectura

```
n8n ──HTTP──► rag (FastAPI + LlamaIndex) ──► postgres (base "falcon_rag", extensión pgvector)
                     │                              │
                     │                              ├── tabla "clients" (registro de client_id)
                     │                              └── tabla "falcon_documents" (compartida,
                     │                                  cada fila con client_id en su metadata)
                     ├── Embeddings: OpenAI o Ollama (según EMBEDDING_PROVIDER)
                     └── LLM de respuesta: OpenAI o Ollama (según LLM_PROVIDER)
```

- **Un solo contenedor de Postgres** sirve tanto a n8n (base `POSTGRES_DB`)
  como al RAG (base separada `RAG_DB`, con `pgvector` habilitado ahí). Se
  crea automáticamente la primera vez que se levanta el volumen, vía
  `postgres-init/init-rag-db.sh`. Para producción a mayor escala, separar
  en una instancia de Postgres dedicada es razonable, pero no es necesario
  para esta fase.
- **Multitenancy por fila, no por esquema**: en vez de una base o tabla
  separada por cliente, todos los documentos viven en la misma tabla
  `falcon_documents`, con `client_id` guardado en el metadata de cada
  documento. Cada `/ingest` y `/query` exige un `client_id` que debe
  existir en la tabla `clients` (se crea con `POST /clients`); las
  consultas filtran siempre por ese `client_id`, así que un cliente nunca
  ve documentos de otro.
- **Proveedor de embeddings/LLM intercambiable**: por defecto OpenAI
  (rápido de arrancar), con la opción de usar Ollama local para no
  depender de una API externa. Se elige con `EMBEDDING_PROVIDER` /
  `LLM_PROVIDER` en `.env` — no requiere tocar código.
- **Autenticación simple**: Bearer token (`RAG_API_KEY`) igual al que ya
  espera el workflow de n8n. Si no se configura, el servicio queda abierto
  (aceptable solo en desarrollo local). Es una única clave compartida por
  todos los clientes — ver "Pendiente" sobre lo que esto implica.

## Endpoints

| Método | Ruta | Body | Descripción |
|---|---|---|---|
| GET | `/health` | — | Chequeo de vida |
| POST | `/clients` | `{"client_id": "...", "name": "..."}` | Registra (o actualiza el nombre de) un cliente de Falcon |
| POST | `/ingest` | `{"client_id": "...", "documents": [{"id": "...", "text": "...", "metadata": {}}]}` | Indexa uno o más documentos para ese cliente |
| POST | `/query` | `{"client_id": "...", "query": "...", "session_id": "...", "top_k": 4}` | Devuelve `{"answer": "...", "sources": [...]}` filtrado a los documentos de ese cliente |

Los tres endpoints (salvo `/health`) requieren `Authorization: Bearer
$RAG_API_KEY` si esa variable está configurada. `/ingest` y `/query`
devuelven `404` si el `client_id` no existe en la tabla `clients`.

## Cómo probarlo en local

```bash
docker compose up -d --build rag

# 1. Registrar un cliente
curl -X POST http://localhost:${RAG_PORT}/clients \
  -H "Authorization: Bearer $RAG_API_KEY" -H "Content-Type: application/json" \
  -d '{"client_id": "acme", "name": "Acme Corp"}'

# 2. Ingestar un documento para ese cliente
curl -X POST http://localhost:${RAG_PORT}/ingest \
  -H "Authorization: Bearer $RAG_API_KEY" -H "Content-Type: application/json" \
  -d '{"client_id": "acme", "documents": [{"text": "Falcon automatiza WhatsApp, Instagram y CRM con agentes de IA."}]}'

# 3. Consultar, siempre pasando el mismo client_id
curl -X POST http://localhost:${RAG_PORT}/query \
  -H "Authorization: Bearer $RAG_API_KEY" -H "Content-Type: application/json" \
  -d '{"client_id": "acme", "query": "¿Qué automatiza Falcon?"}'
```

## Pendiente / próximos pasos

- **`RAG_API_KEY` es una sola clave compartida por todos los clientes**:
  quien la tenga puede leer/escribir en cualquier `client_id` con solo
  cambiar ese campo en el body. El `client_id` hoy es aislamiento de
  *datos*, no de *autenticación* — el paso natural siguiente es una clave
  por cliente (o un JWT que la incluya), en vez de confiar en el valor que
  manda quien llama.
- `postgres-init/init-rag-db.sh` solo corre en el primer arranque de un
  volumen nuevo (semántica de `docker-entrypoint-initdb.d`). En un
  deployment que ya tenga datos, la tabla `clients` no se crea sola — hay
  que aplicarla a mano o migrar a una herramienta de migraciones real
  antes de que haya datos en producción.
- El workflow de n8n (`workflows/whatsapp-rag-inbound.json`) todavía **no
  manda `client_id`** al llamar a `/query` — sigue siendo de un solo
  tenant (una instancia de n8n por cliente de Falcon). Enrutar múltiples
  clientes desde una misma instancia de n8n (ej. mapeando
  `phone_number_id` del webhook de Meta a un `client_id`) es una fase
  aparte, todavía no implementada.
- No hay endpoint de ingesta masiva desde archivos (PDF, docx, etc.) — hoy
  solo acepta texto plano ya extraído. Se puede sumar `MarkItDown` (de la
  tabla de herramientas evaluadas en la Fase de research) como paso previo
  de conversión antes de llamar a `/ingest`.
- Sin control de duplicados ni actualización de documentos existentes
  (cada `/ingest` inserta, no hace upsert).
- `EMBEDDING_DIM` debe coincidir con el modelo elegido (1536 para
  `text-embedding-3-small` de OpenAI; los modelos de Ollama suelen ser
  768 — ajustar la variable si se cambia de proveedor con datos ya
  indexados implica reindexar todo).
