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
  POST /clients      -> registra un client_id nuevo
  POST /ingest       -> agrega documentos al índice, asociados a un client_id
  POST /query        -> responde una pregunta usando los documentos de ese client_id
  POST /interactions -> registra una interacción (mensaje + respuesta) en el
                        historial del agente (tabla agente_interacciones)
  POST /handoffs     -> deriva una conversación a una persona y pausa el bot
                        con ese número (tabla conversaciones_derivadas)
  GET  /handoffs/status -> indica si el bot está en pausa con un número
  DELETE /handoffs   -> reactiva el bot con un número antes de que venza la pausa
  POST /v1/audio/transcriptions -> transcribe un audio con Gemini; misma forma
                        que la API de Whisper, así n8n lo usa sin cambios
  POST /v1/voice-replies -> convierte una respuesta en nota de voz (ElevenLabs),
                        la sube a WhatsApp y devuelve el media_id

Memoria: /query lee las últimas interacciones del mismo número
(agente_interacciones) y responde como una conversación, no como una
pregunta suelta. Si el modelo no encuentra la respuesta en los documentos,
o el cliente quiere comprar o hablar con una persona, /query devuelve
`handoff: true` y n8n deriva la conversación (ver workflows/README.md).
"""

import os
from urllib.parse import urlparse

import psycopg2
from fastapi import Depends, FastAPI, File, Form, HTTPException, Header, UploadFile
from pydantic import BaseModel

from llama_index.core import Document, Settings, StorageContext, VectorStoreIndex
from llama_index.core.chat_engine import CondensePlusContextChatEngine
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from llama_index.vector_stores.postgres import PGVectorStore

RAG_API_KEY = os.environ.get("RAG_API_KEY")
DATABASE_URL = os.environ["DATABASE_URL"]
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "openai")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
EMBED_DIM = int(os.environ.get("EMBEDDING_DIM", "1536"))
TABLE_NAME = "falcon_documents"
# Cuántos intercambios previos del mismo número se le pasan al modelo, y
# desde hace cuánto: una conversación de ayer no debería contaminar la de hoy.
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "6"))
HISTORY_HOURS = int(os.environ.get("HISTORY_HOURS", "24"))
HANDOFF_PAUSE_HOURS = int(os.environ.get("HANDOFF_PAUSE_HOURS", "12"))
HANDOFF_MARKER = "[DERIVAR]"
# Sobre este largo la respuesta va en texto: un audio de más de ~40 s de un
# bot cansa más de lo que ayuda.
VOICE_MAX_CHARS = int(os.environ.get("VOICE_MAX_CHARS", "600"))

SYSTEM_PROMPT = """Eres el asistente de WhatsApp de {business}. Respondes en español, \
en tono cercano y breve (mensajes de WhatsApp: 1 a 4 frases, sin markdown).

Reglas:
- Usa solo la información del contexto y de la conversación. No inventes \
precios, plazos, productos ni políticas.
- Si la respuesta no está en el contexto, o el cliente quiere comprar, hacer \
un pedido, pedir una cotización o hablar con una persona, responde \
únicamente {marker} y nada más.
- Si el cliente solo saluda, salúdalo y pregúntale en qué lo puedes ayudar."""


def _configure_settings() -> None:
    if EMBEDDING_PROVIDER == "gemini":
        from gemini import gemini_embedding

        Settings.embed_model = gemini_embedding(EMBED_DIM)
    elif EMBEDDING_PROVIDER == "ollama":
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

    if LLM_PROVIDER == "gemini":
        from gemini import gemini_llm

        Settings.llm = gemini_llm()
    elif LLM_PROVIDER == "ollama":
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


def _ensure_schema() -> None:
    """Crea las tablas propias del servicio si no existen.

    En Coolify el bind mount de postgres-init/ no se monta, así que no se
    puede depender de init-rag-db.sh para las tablas. Todo es idempotente.
    La base (RAG_DB) y la extensión vector sí tienen que existir antes.
    """
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    client_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
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
                CREATE INDEX IF NOT EXISTS idx_agente_interacciones_from_number
                    ON agente_interacciones (client_id, from_number, created_at);
                CREATE TABLE IF NOT EXISTS conversaciones_derivadas (
                    client_id TEXT NOT NULL REFERENCES clients (client_id),
                    from_number TEXT NOT NULL,
                    reason TEXT,
                    summary TEXT,
                    paused_until TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (client_id, from_number)
                );
                """
            )


_configure_settings()
_ensure_schema()
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


def _client_name(client_id: str) -> str:
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM clients WHERE client_id = %s", (client_id,))
            row = cur.fetchone()
    return row[0] if row else client_id


def _recent_turns(client_id: str, from_number: str, limit: int) -> list[tuple[str | None, str | None]]:
    """Últimos intercambios (mensaje, respuesta) con ese número, del más viejo al más nuevo."""
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_message, agent_response
                FROM agente_interacciones
                WHERE client_id = %s
                  AND from_number = %s
                  AND created_at > now() - make_interval(hours => %s)
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (client_id, from_number, HISTORY_HOURS, limit),
            )
            rows = cur.fetchall()
    return list(reversed(rows))


def _chat_history(client_id: str, from_number: str | None) -> list[ChatMessage]:
    if not from_number or HISTORY_LIMIT <= 0:
        return []
    history: list[ChatMessage] = []
    for user_message, agent_response in _recent_turns(client_id, from_number, HISTORY_LIMIT):
        if user_message:
            history.append(ChatMessage(role=MessageRole.USER, content=user_message))
        # Los mensajes recibidos con el bot en pausa no tienen respuesta.
        if agent_response:
            history.append(ChatMessage(role=MessageRole.ASSISTANT, content=agent_response))
    return history


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
    # Número de WhatsApp del cliente final: se usa para leer su historial.
    session_id: str | None = None
    top_k: int = 4


class QueryResponse(BaseModel):
    answer: str
    sources: list[str] = []
    # True cuando el bot no debe responder solo: n8n deriva a una persona.
    handoff: bool = False


class HandoffCreateRequest(BaseModel):
    client_id: str
    from_number: str
    reason: str | None = None
    contact_name: str | None = None
    # El mensaje que disparó la derivación todavía no está en el historial.
    last_message: str | None = None


class HandoffResponse(BaseModel):
    client_id: str
    from_number: str
    paused: bool
    paused_until: str | None = None
    summary: str | None = None


class InteractionCreateRequest(BaseModel):
    client_id: str
    channel: str = "whatsapp"
    from_number: str | None = None
    intent: str | None = None
    user_message: str | None = None
    agent_response: str | None = None
    wa_message_id: str | None = None
    session_id: str | None = None


class InteractionResponse(BaseModel):
    id: int
    client_id: str
    created_at: str


class TranscriptionResponse(BaseModel):
    text: str


class VoiceReplyRequest(BaseModel):
    text: str
    voice_id: str | None = None  # por defecto ELEVENLABS_VOICE_ID
    phone_number_id: str | None = None  # por defecto WHATSAPP_PHONE_NUMBER_ID


class VoiceReplyResponse(BaseModel):
    media_id: str
    characters: int


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
    retriever = index.as_retriever(similarity_top_k=payload.top_k, filters=filters)
    chat_engine = CondensePlusContextChatEngine.from_defaults(
        retriever=retriever,
        system_prompt=SYSTEM_PROMPT.format(
            business=_client_name(payload.client_id), marker=HANDOFF_MARKER
        ),
    )
    result = chat_engine.chat(
        payload.query,
        chat_history=_chat_history(payload.client_id, payload.session_id),
    )
    answer = str(result).strip()
    sources = [node.node.get_content()[:200] for node in result.source_nodes]
    if HANDOFF_MARKER in answer:
        return QueryResponse(answer="", sources=sources, handoff=True)
    return QueryResponse(answer=answer, sources=sources)


@app.post(
    "/interactions",
    response_model=InteractionResponse,
    dependencies=[Depends(require_api_key)],
)
def create_interaction(payload: InteractionCreateRequest) -> InteractionResponse:
    require_known_client(payload.client_id)
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agente_interacciones
                    (client_id, channel, from_number, intent, user_message,
                     agent_response, wa_message_id, session_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, client_id, created_at
                """,
                (
                    payload.client_id,
                    payload.channel,
                    payload.from_number,
                    payload.intent,
                    payload.user_message,
                    payload.agent_response,
                    payload.wa_message_id,
                    payload.session_id,
                ),
            )
            row = cur.fetchone()
    return InteractionResponse(id=row[0], client_id=row[1], created_at=row[2].isoformat())


def _handoff_summary(payload: HandoffCreateRequest) -> str:
    lines = [f"Cliente: {payload.contact_name or 'sin nombre'} (+{payload.from_number})"]
    messages = [m for m, _ in _recent_turns(payload.client_id, payload.from_number, 3) if m]
    if payload.last_message:
        messages.append(payload.last_message)
    lines += [f"- {m[:200]}" for m in messages]
    return "\n".join(lines)


@app.post("/handoffs", response_model=HandoffResponse, dependencies=[Depends(require_api_key)])
def create_handoff(payload: HandoffCreateRequest) -> HandoffResponse:
    require_known_client(payload.client_id)
    summary = _handoff_summary(payload)
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversaciones_derivadas
                    (client_id, from_number, reason, summary, paused_until)
                VALUES (%s, %s, %s, %s, now() + make_interval(hours => %s))
                ON CONFLICT (client_id, from_number) DO UPDATE SET
                    reason = EXCLUDED.reason,
                    summary = EXCLUDED.summary,
                    paused_until = EXCLUDED.paused_until,
                    created_at = now()
                RETURNING paused_until
                """,
                (
                    payload.client_id,
                    payload.from_number,
                    payload.reason,
                    summary,
                    HANDOFF_PAUSE_HOURS,
                ),
            )
            paused_until = cur.fetchone()[0]
    return HandoffResponse(
        client_id=payload.client_id,
        from_number=payload.from_number,
        paused=True,
        paused_until=paused_until.isoformat(),
        summary=summary,
    )


@app.get("/handoffs/status", response_model=HandoffResponse, dependencies=[Depends(require_api_key)])
def handoff_status(client_id: str, from_number: str) -> HandoffResponse:
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT paused_until FROM conversaciones_derivadas
                WHERE client_id = %s AND from_number = %s AND paused_until > now()
                """,
                (client_id, from_number),
            )
            row = cur.fetchone()
    return HandoffResponse(
        client_id=client_id,
        from_number=from_number,
        paused=row is not None,
        paused_until=row[0].isoformat() if row else None,
    )


@app.delete("/handoffs", response_model=HandoffResponse, dependencies=[Depends(require_api_key)])
def delete_handoff(client_id: str, from_number: str) -> HandoffResponse:
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM conversaciones_derivadas WHERE client_id = %s AND from_number = %s",
                (client_id, from_number),
            )
    return HandoffResponse(client_id=client_id, from_number=from_number, paused=False)


@app.post(
    "/v1/audio/transcriptions",
    response_model=TranscriptionResponse,
    dependencies=[Depends(require_api_key)],
)
def transcribe_audio(
    file: UploadFile = File(...),
    model: str | None = Form(default=None),  # lo manda n8n (formato Whisper); se ignora
) -> TranscriptionResponse:
    from gemini import transcribe

    # WhatsApp manda "audio/ogg; codecs=opus"; Gemini quiere el tipo sin parámetros.
    mime_type = (file.content_type or "audio/ogg").split(";")[0].strip()
    if mime_type in ("", "application/octet-stream"):
        mime_type = "audio/ogg"
    try:
        text = transcribe(file.file.read(), mime_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo transcribir: {exc}") from exc
    return TranscriptionResponse(text=text)


@app.post(
    "/v1/voice-replies",
    response_model=VoiceReplyResponse,
    dependencies=[Depends(require_api_key)],
)
def voice_reply(payload: VoiceReplyRequest) -> VoiceReplyResponse:
    from voice import clean_for_speech, synthesize, upload_to_whatsapp

    text = clean_for_speech(payload.text)
    if not text:
        raise HTTPException(status_code=422, detail="No hay texto para leer en voz alta")
    if len(text) > VOICE_MAX_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Respuesta de {len(text)} caracteres; el máximo para voz es {VOICE_MAX_CHARS}",
        )
    try:
        audio = synthesize(text, payload.voice_id)
        media_id = upload_to_whatsapp(audio, payload.phone_number_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo generar la nota de voz: {exc}") from exc
    return VoiceReplyResponse(media_id=media_id, characters=len(text))
