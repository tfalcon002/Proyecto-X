# Falcon RAG Service (Fase 3)

Microservicio de ingesta y consulta de documentos, usado internamente por
n8n para responder preguntas con contexto propio (ver
`workflows/whatsapp-rag-inbound.json`, nodo "Query RAG (LlamaIndex)").

## Arquitectura

```
n8n ──HTTP──► rag (FastAPI + LlamaIndex) ──► postgres (base "falcon_rag", extensión pgvector)
                     │
                     ├── Embeddings: OpenAI o Ollama (según EMBEDDING_PROVIDER)
                     └── LLM de respuesta: OpenAI o Ollama (según LLM_PROVIDER)
```

- **Un solo contenedor de Postgres** sirve tanto a n8n (base `POSTGRES_DB`)
  como al RAG (base separada `RAG_DB`, con `pgvector` habilitado ahí). Se
  crea automáticamente la primera vez que se levanta el volumen, vía
  `postgres-init/init-rag-db.sh`. Para producción a mayor escala, separar
  en una instancia de Postgres dedicada es razonable, pero no es necesario
  para esta fase.
- **Proveedor de embeddings/LLM intercambiable**: por defecto OpenAI
  (rápido de arrancar), con la opción de usar Ollama local para no
  depender de una API externa. Se elige con `EMBEDDING_PROVIDER` /
  `LLM_PROVIDER` en `.env` — no requiere tocar código.
- **Autenticación simple**: Bearer token (`RAG_API_KEY`) igual al que ya
  espera el workflow de n8n. Si no se configura, el servicio queda abierto
  (aceptable solo en desarrollo local).

## Endpoints

| Método | Ruta | Body | Descripción |
|---|---|---|---|
| GET | `/health` | — | Chequeo de vida |
| POST | `/ingest` | `{"documents": [{"id": "...", "text": "...", "metadata": {}}]}` | Indexa uno o más documentos |
| POST | `/query` | `{"query": "...", "session_id": "...", "top_k": 4}` | Devuelve `{"answer": "...", "sources": [...]}` |

Ambos endpoints requieren `Authorization: Bearer $RAG_API_KEY` si esa
variable está configurada.

## Cómo probarlo en local

```bash
docker compose up -d --build rag
curl -X POST http://localhost:${RAG_PORT}/ingest \
  -H "Authorization: Bearer $RAG_API_KEY" -H "Content-Type: application/json" \
  -d '{"documents": [{"text": "Falcon automatiza WhatsApp, Instagram y CRM con agentes de IA."}]}'

curl -X POST http://localhost:${RAG_PORT}/query \
  -H "Authorization: Bearer $RAG_API_KEY" -H "Content-Type: application/json" \
  -d '{"query": "¿Qué automatiza Falcon?"}'
```

## Pendiente / próximos pasos

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
