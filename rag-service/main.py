"""
Falcon RAG service.

Microservicio de ingesta y consulta de documentos sobre LlamaIndex,
con pgvector (Postgres) como almacén vectorial. Pensado para ser
llamado internamente por n8n (ver workflows/whatsapp-rag-inbound.json).

Multitenant: todos los clientes de Falcon comparten la misma tabla de
documentos (`falcon_documents`), separados por `client_id` (guardado en
el metadata de cada documento y usado para filtrar cada consulta). El
`client_id` debe existir en la tabla `clients` (ver postgres-init/) antes
de poder ingestar o consultar.

Endpoints:
  GET  /health
  POST /clients -> registra un client_id nuevo
  POST /ingest  -> agrega documentos al índice, asociados a un client_id
  POST /query   -> responde una pregunta usando los documentos de ese client_id
"""

import os
from urllib.parse import urlparse

import psycopg2
from fastapi import Depends, FastAPI, HTTPException, Header
from pydantic import BaseModel

from llama_index.core import Document, Settings, StorageContext, VectorStoreIndex
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from llama_index.vector_stores.postgres import PGVectorStore

RAG_API_KEY = os.environ.get("RAG_API_KEY")
DATABASE_URL = os.environ["DATABASE_URL"]
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "openai")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
EMBED_DIM = int(os.environ.get("EMBEDDING_DIM", "1536"))
TABLE_NAME = "falcon_documents"


def _configure_settings() -> None:
    if EMBEDDING_PROVIDER == "ollama":
        from llama_index.embeddings.ollama import OllamaEmbedding

        Settings.embed_model = OllamaEmbedding(
            model_name=EMBEDDING_MODEL,
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434"),
        )
    else:
        from llama_index.embeddings.openai import OpenAIEmbedding

        Settings.embed_model = OpenAIEmbedding(
            model=EMBEDDING_MODEL,
            api_key=os.environ.get("OPENAI_API_KEY"),
        )

    if LLM_PROVIDER == "ollama":
        from llama_index.llms.ollama import Ollama

        Settings.llm = Ollama(
            model=os.environ.get("OLLAMA_LLM_MODEL", "llama3.1"),
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434"),
            request_timeout=120.0,
        )
    else:
        from llama_index.llms.openai import OpenAI

        Settings.llm = OpenAI(
            model=os.environ.get("OPENAI_LLM_MODEL", "gpt-4o-mini"),
            api_key=os.environ.get("OPENAI_API_KEY"),
        )


def _vector_store() -> PGVectorStore:
    parsed = urlparse(DATABASE_URL)
    return PGVectorStore.from_params(
        database=parsed.path.lstrip("/"),
        host=parsed.hostname,
        port=str(parsed.port or 5432),
        user=parsed.username,
        password=parsed.password,
        table_name=TABLE_NAME,
        embed_dim=EMBED_DIM,
    )


_configure_settings()
_index: VectorStoreIndex | None = None


def get_index() -> VectorStoreIndex:
    global _index
    if _index is None:
        storage_context = StorageContext.from_defaults(vector_store=_vector_store())
        _index = VectorStoreIndex.from_vector_store(
            vector_store=storage_context.vector_store
        )
    return _index


def require_api_key(authorization: str = Header(default="")) -> None:
    if not RAG_API_KEY:
        return  # sin clave configurada: servicio abierto (solo para dev local)
    expected = f"Bearer {RAG_API_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _client_exists(client_id: str) -> bool:
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM clients WHERE client_id = %s", (client_id,))
            return cur.fetchone() is not None


def require_known_client(client_id: str) -> None:
    if not _client_exists(client_id):
        raise HTTPException(status_code=404, detail=f"Unknown client_id: {client_id}")


app = FastAPI(title="Falcon RAG Service")


class ClientCreateRequest(BaseModel):
    client_id: str
    name: str


class ClientResponse(BaseModel):
    client_id: str
    name: str


class IngestDocument(BaseModel):
    id: str | None = None
    text: str
    metadata: dict = {}


class IngestRequest(BaseModel):
    client_id: str
    documents: list[IngestDocument]


class IngestResponse(BaseModel):
    ingested: int


class QueryRequest(BaseModel):
    client_id: str
    query: str
    session_id: str | None = None
    top_k: int = 4


class QueryResponse(BaseModel):
    answer: str
    sources: list[str] = []


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/clients", response_model=ClientResponse, dependencies=[Depends(require_api_key)])
def create_client(payload: ClientCreateRequest) -> ClientResponse:
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO clients (client_id, name)
                VALUES (%s, %s)
                ON CONFLICT (client_id) DO UPDATE SET name = EXCLUDED.name
                """,
                (payload.client_id, payload.name),
            )
    return ClientResponse(client_id=payload.client_id, name=payload.name)


@app.post("/ingest", response_model=IngestResponse, dependencies=[Depends(require_api_key)])
def ingest(payload: IngestRequest) -> IngestResponse:
    require_known_client(payload.client_id)
    documents = [
        Document(
            # Prefijado con el client_id para que dos clientes no puedan
            # pisarse el mismo doc_id en la tabla compartida.
            doc_id=f"{payload.client_id}:{doc.id}" if doc.id else None,
            text=doc.text,
            metadata={**doc.metadata, "client_id": payload.client_id},
        )
        for doc in payload.documents
    ]
    index = get_index()
    for document in documents:
        index.insert(document)
    return IngestResponse(ingested=len(documents))


@app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_api_key)])
def query(payload: QueryRequest) -> QueryResponse:
    require_known_client(payload.client_id)
    index = get_index()
    filters = MetadataFilters(filters=[MetadataFilter(key="client_id", value=payload.client_id)])
    query_engine = index.as_query_engine(similarity_top_k=payload.top_k, filters=filters)
    result = query_engine.query(payload.query)
    sources = [node.node.get_content()[:200] for node in result.source_nodes]
    return QueryResponse(answer=str(result), sources=sources)
