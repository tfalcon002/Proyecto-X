"""
Gemini (Google AI Studio) como proveedor del RAG.

- Respuestas: endpoint compatible con OpenAI de Gemini, reutilizando la clase
  OpenAI de LlamaIndex (no conoce los modelos de Gemini, por eso se fija su
  metadata a mano).
- Embeddings y transcripción de audio: API REST nativa de Gemini, que permite
  elegir la dimensión del vector y recibe audio .ogg de WhatsApp tal cual.

Todo se configura con GEMINI_API_KEY y los GEMINI_* de .env.example.
"""

import base64
import os

import httpx
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.base.llms.types import LLMMetadata
from llama_index.llms.openai import OpenAI

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_OPENAI_BASE = f"{GEMINI_API_BASE}/openai/"
GEMINI_LLM_MODEL = os.environ.get("GEMINI_LLM_MODEL") or "gemini-3.5-flash-lite"
GEMINI_EMBEDDING_MODEL = os.environ.get("GEMINI_EMBEDDING_MODEL") or "gemini-embedding-001"
GEMINI_TRANSCRIBE_MODEL = os.environ.get("GEMINI_TRANSCRIBE_MODEL") or GEMINI_LLM_MODEL
TIMEOUT = 60.0

TRANSCRIBE_PROMPT = (
    "Transcribe este audio de WhatsApp tal como se dijo, en su idioma original. "
    "Devuelve solo la transcripción, sin comentarios. Si no se entiende nada, "
    "devuelve un texto vacío."
)


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Falta GEMINI_API_KEY")
    return key


def _post(path: str, body: dict) -> dict:
    response = httpx.post(
        f"{GEMINI_API_BASE}/{path}",
        json=body,
        headers={"x-goog-api-key": _api_key()},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


class GeminiLLM(OpenAI):
    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=1_000_000,
            num_output=self.max_tokens or -1,
            is_chat_model=True,
            is_function_calling_model=True,
            model_name=self.model,
        )


def gemini_llm() -> GeminiLLM:
    return GeminiLLM(model=GEMINI_LLM_MODEL, api_key=_api_key(), api_base=GEMINI_OPENAI_BASE)


class GeminiEmbedding(BaseEmbedding):
    dimensions: int

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        model = f"models/{self.model_name}"
        data = _post(
            f"{model}:batchEmbedContents",
            {
                "requests": [
                    {
                        "model": model,
                        "content": {"parts": [{"text": text}]},
                        "taskType": task_type,
                        "outputDimensionality": self.dimensions,
                    }
                    for text in texts
                ]
            },
        )
        return [item["values"] for item in data["embeddings"]]

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed([query], "RETRIEVAL_QUERY")[0]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_DOCUMENT")[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)


def gemini_embedding(dimensions: int) -> GeminiEmbedding:
    # La API acepta hasta 100 textos por llamada.
    return GeminiEmbedding(
        model_name=GEMINI_EMBEDDING_MODEL, dimensions=dimensions, embed_batch_size=100
    )


def transcribe(audio: bytes, mime_type: str) -> str:
    data = _post(
        f"models/{GEMINI_TRANSCRIBE_MODEL}:generateContent",
        {
            "contents": [
                {
                    "parts": [
                        {"text": TRANSCRIBE_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64.b64encode(audio).decode(),
                            }
                        },
                    ]
                }
            ]
        },
    )
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts") or []
    return "".join(part.get("text", "") for part in parts).strip()
