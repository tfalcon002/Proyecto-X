# Workflows n8n — Falcon

## `whatsapp-rag-inbound.json` (Fase 2)

Primer flujo real de automatización: recibe mensajes de WhatsApp (Meta Cloud
API), transcribe audio si aplica, consulta el motor RAG (LlamaIndex) y
responde al usuario por WhatsApp.

### Diagrama del flujo

```
Meta Verify (GET)  ──► Check Verify Token ──► Respond Challenge / Reject Verify
                                               (handshake inicial de Meta)

Meta Events (POST) ──► Extract Message ──► Has Message? ──(no)──► Ack No-op
                                               │(sí)
                                               ▼
                                          Is Audio?
                                          │           │
                                   (sí)  ▼             ▼ (no)
                            Get Media URL          Use Text As-Is
                                   │                     │
                            Download Audio                │
                                   │                     │
                          Whisper Transcribe              │
                                   └────────┬─────────────┘
                                            ▼
                                       Merge Text
                                            ▼
                                Query RAG (LlamaIndex)
                                            ▼
                                       Format Reply
                                            ▼
                                  Send WhatsApp Reply
                                            ▼
                                        Ack Event
```

### Importar en n8n

1. Abrir n8n → menú (⋮) → **Import from File** → seleccionar
   `workflows/whatsapp-rag-inbound.json`.
2. Revisar cada nodo `HTTP Request` una vez importado — los nombres de
   parámetros de autenticación/body pueden variar levemente según la
   versión de n8n; el nodo `Merge Text` en particular conviene confirmarlo
   manualmente (modo "Choose Branch": debe tomar los datos de la rama que
   sí se ejecutó, audio o texto).
3. Activar el workflow solo después de configurar las variables de entorno
   (siguiente sección) y el webhook en Meta.

### Variables de entorno requeridas

Este workflow lee credenciales vía `$env` dentro de n8n — **agregar estas
variables al `environment` del servicio `n8n` en `docker-compose.yml` (o al
`.env`) una vez que el PR #3 de infraestructura esté mergeado**. No se
tocan esos archivos en este PR para evitar conflicto con uno abierto en
paralelo.

| Variable | Uso | Dónde conseguirla |
|---|---|---|
| `WHATSAPP_VERIFY_TOKEN` | Token que Meta envía en el handshake `GET` para verificar el webhook | Lo defines tú; debe coincidir con el que pongas en el dashboard de Meta |
| `WHATSAPP_ACCESS_TOKEN` | Bearer token para llamar a la Graph API (leer media, enviar mensajes) | Meta App → WhatsApp → API Setup (usar un token de **usuario del sistema**, no el temporal de 24h) |
| `WHATSAPP_PHONE_NUMBER_ID` | ID del número de WhatsApp Business que envía las respuestas | Meta App → WhatsApp → API Setup |
| `META_GRAPH_API_VERSION` | Versión de la Graph API a usar (ej. `v20.0`) | Documentación de Meta, actualizar periódicamente |
| `WHISPER_API_URL` | Endpoint compatible con la API de transcripción de OpenAI (`/v1/audio/transcriptions`) | Servidor propio (Whisper self-hosted) o `https://api.openai.com` |
| `WHISPER_API_KEY` | Bearer token del servicio anterior | Vacío si el servidor local no exige auth |
| `WHISPER_MODEL` | Nombre del modelo a usar (default `whisper-1` en el nodo si no se define) | Depende del servidor Whisper elegido |
| `RAG_API_URL` | Endpoint del servicio RAG/LlamaIndex que responde `{ "answer": "..." }` | Servicio interno de Falcon (aún por desplegar) |
| `RAG_API_KEY` | Bearer token del servicio RAG, si aplica | Interno |

### Configurar el webhook en Meta

En el dashboard de la app de Meta (WhatsApp → Configuration):

- **Callback URL**: `https://<tu-dominio-n8n>/webhook/whatsapp/webhook`
- **Verify token**: el mismo valor que pusiste en `WHATSAPP_VERIFY_TOKEN`
- Suscribir el campo `messages`.

### Pendiente / próximos pasos

- El endpoint `RAG_API_URL` todavía no existe — hoy el flujo fallará en el
  nodo "Query RAG (LlamaIndex)" hasta que se despliegue ese servicio.
- No valida la firma `X-Hub-Signature-256` de Meta (recomendado antes de
  producción, para confirmar que el request viene realmente de Meta).
- Responde de forma síncrona (Meta espera la respuesta del webhook antes
  de los ~20s de timeout); si la consulta RAG es lenta, conviene separar
  en "ack inmediato" + procesamiento asíncrono en un flujo aparte.
