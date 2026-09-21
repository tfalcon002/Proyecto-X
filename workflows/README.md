# Workflows n8n — Falcon

## `whatsapp-rag-inbound.json` (Fase 2 + Fase 4)

Flujo principal de automatización: recibe mensajes de WhatsApp (Meta Cloud
API), transcribe audio si aplica, y enruta el mensaje según intención —
pregunta general (RAG/LlamaIndex), consulta de disponibilidad o confirmación
de cita (Cal.com) — y responde al usuario por WhatsApp. Al confirmar una cita
además dispara una notificación multicanal vía Novu.

### Diagrama del flujo

```
Meta Verify (GET)  ──► Check Verify Token ──► Respond Challenge / Reject Verify
                                               (handshake inicial de Meta)

Meta Events (POST) ──► Compute + Verify Signature ──(inválida)──► 403 Forbidden
                                    │(válida)
                                    ▼
                            Extract Message ──► Has Message? ──(no)──► Ack No-op
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
                                     Detect Intent
                                            ▼
                                    Route by Intent
                    ┌───────────────────┼───────────────────┐
              (booking)           (availability)          (rag, default)
                    ▼                    ▼                    ▼
        Extract Booking Details   Compute Availability   Query RAG (LlamaIndex)
                    ▼                    Window                 ▼
          Has Booking Details?           ▼                Format Reply
           │              │      Get Cal.com Availability        │
      (sí) ▼         (no) ▼              ▼                       │
  Book Cal.com    Format Missing   Format Availability            │
  Appointment     Details Reply         Reply                    │
     │      │            │               │                       │
     ▼      ▼            └───────────────┴───────────┬───────────┘
Format    Trigger Novu                                ▼
Booking   Notification                       Send WhatsApp Reply
Confirm.  (fire-and-forget)                            ▼
     │                                              Ack Event
     └──────────────────────────────────────────────────┘
```

La clasificación de intención (`Detect Intent`) es por palabras clave — ver
"Pendiente" más abajo para la limitación y el camino de mejora.

### Verificación de firma de Meta (`X-Hub-Signature-256`)

Antes de procesar cualquier evento `POST`, el workflow valida que el request
venga realmente de Meta:

1. `Meta Events (POST)` tiene activado `rawBody` en sus opciones — necesario
   porque la firma se calcula sobre los bytes exactos del body, no sobre el
   JSON ya parseado (re-serializarlo puede cambiar espacios/orden y romper
   la comparación).
2. `Compute Meta Signature` (nodo `Crypto`, no un `Code` node) calcula el
   HMAC-SHA256 del raw body usando `WHATSAPP_APP_SECRET` como clave.
3. `Verify Meta Signature` compara ese resultado (con el prefijo `sha256=`)
   contra el header `X-Hub-Signature-256` que mandó Meta, y reconstruye el
   `body` a partir del raw body ya verificado (no del parseo automático de
   n8n), para que lo que llega a `Extract Message` sea exactamente lo que
   Meta firmó.
4. `Signature Valid?` corta el flujo con `403 Forbidden` si no coincide —
   **falla cerrado**: si `WHATSAPP_APP_SECRET` está vacío, todos los eventos
   se rechazan (ver tabla de variables).

`WHATSAPP_APP_SECRET` **no es el mismo valor** que `WHATSAPP_ACCESS_TOKEN`:
es el "App Secret" de la app de Meta (Configuración → Básica), no un token
de acceso a la Graph API.

### Importar en n8n

1. Abrir n8n → menú (⋮) → **Import from File** → seleccionar
   `workflows/whatsapp-rag-inbound.json`.
2. Revisar cada nodo `HTTP Request` una vez importado — los nombres de
   parámetros de autenticación/body pueden variar levemente según la
   versión de n8n; el nodo `Merge Text` en particular conviene confirmarlo
   manualmente (modo "Choose Branch": debe tomar los datos de la rama que
   sí se ejecutó, audio o texto). Lo mismo con `Compute Meta Signature`
   (nodo `Crypto`): confirmar que quedaron seleccionados "HMAC" / "SHA256" /
   modo binario sobre la propiedad `data`, ya que los nombres exactos de
   estos campos varían entre versiones de n8n.
3. Activar el workflow solo después de configurar las variables de entorno
   (siguiente sección) y el webhook en Meta.

### Variables de entorno requeridas

Este workflow lee credenciales vía `$env` dentro de n8n. Ya están conectadas
en el `environment` del servicio `n8n` en `docker-compose.yml` — solo hace
falta completarlas en tu `.env` (ver `.env.example`).

| Variable | Uso | Dónde conseguirla |
|---|---|---|
| `WHATSAPP_VERIFY_TOKEN` | Token que Meta envía en el handshake `GET` para verificar el webhook | Lo defines tú; debe coincidir con el que pongas en el dashboard de Meta |
| `WHATSAPP_ACCESS_TOKEN` | Bearer token para llamar a la Graph API (leer media, enviar mensajes) | Meta App → WhatsApp → API Setup (usar un token de **usuario del sistema**, no el temporal de 24h) |
| `WHATSAPP_PHONE_NUMBER_ID` | ID del número de WhatsApp Business que envía las respuestas | Meta App → WhatsApp → API Setup |
| `META_GRAPH_API_VERSION` | Versión de la Graph API a usar (ej. `v20.0`) | Documentación de Meta, actualizar periódicamente |
| `WHATSAPP_APP_SECRET` | Clave para validar la firma `X-Hub-Signature-256` de cada webhook entrante | Meta App → Configuración → Básica (**no** es `WHATSAPP_ACCESS_TOKEN`) |
| `WHISPER_API_URL` | Endpoint compatible con la API de transcripción de OpenAI (`/v1/audio/transcriptions`) | Servidor propio (Whisper self-hosted) o `https://api.openai.com` |
| `WHISPER_API_KEY` | Bearer token del servicio anterior | Vacío si el servidor local no exige auth |
| `WHISPER_MODEL` | Nombre del modelo a usar (default `whisper-1` en el nodo si no se define) | Depende del servidor Whisper elegido |
| `RAG_API_URL` | Endpoint del servicio RAG/LlamaIndex que responde `{ "answer": "..." }` | Servicio interno de Falcon (`rag-service/`) |
| `RAG_API_KEY` | Bearer token del servicio RAG, si aplica | Interno |
| `CALCOM_API_URL` | Base de la API v2 de Cal.com | Normalmente `https://api.cal.com/v2` |
| `CALCOM_API_KEY` | Bearer token para leer disponibilidad y crear reservas | Cal.com → Settings → Developer → API Keys |
| `CALCOM_API_VERSION` | Valor del header `cal-api-version` que exige la API v2 | Cal.com → docs de versionado de la API |
| `CALCOM_EVENT_TYPE_ID` | ID numérico del tipo de evento a agendar | Cal.com → Event Types → el evento elegido → URL del editor |
| `CALCOM_TIMEZONE` | Zona horaria (IANA) usada al crear la reserva | Ej. `America/Mexico_City` |
| `NOVU_API_URL` | Base de la API de Novu | Normalmente `https://api.novu.co` |
| `NOVU_API_KEY` | API key para disparar notificaciones (`Authorization: ApiKey <key>`) | Novu → Settings → API Keys |
| `NOVU_WORKFLOW_ID` | Identificador del Workflow de Novu que define los canales de la notificación de confirmación | Novu Dashboard → Workflows |

### Cal.com: disponibilidad y agendado desde el chat

Después de `Detect Intent` (clasificación por palabras clave sobre el texto
ya transcripto), `Route by Intent` separa el mensaje en tres caminos:

- **`availability`** (palabras como "disponibilidad", "horarios", "cita",
  "agendar", "schedule"...): `Compute Availability Window` calcula una
  ventana de los próximos 7 días y `Get Cal.com Availability` llama a
  `GET /slots` de Cal.com v2; `Format Availability Reply` arma una lista de
  hasta 5 horarios y le pide al usuario que responda con la fecha/hora
  elegida **junto a su email**, en un solo mensaje (ej.
  `2026-09-10T15:00 tu-email@ejemplo.com`).
- **`booking`** (el mensaje trae fecha/hora + email, o palabras como
  "confirmar"/"reservar"): `Extract Booking Details` parsea ambos datos con
  regex. Si faltan, `Format Missing Details Reply` se los vuelve a pedir. Si
  están completos, `Book Cal.com Appointment` llama a `POST /bookings` de
  Cal.com v2; `Format Booking Confirmation` arma la respuesta de éxito o de
  error según lo que devuelva Cal.com.
- **`rag`** (todo lo demás, comportamiento por default): sigue el camino
  original de la Fase 2 (consulta al servicio RAG).

Al completar una reserva (éxito o error), `Book Cal.com Appointment` dispara
en paralelo `Trigger Novu Notification` (fire-and-forget: su falla no
bloquea la respuesta al usuario por WhatsApp) contra
`POST /v1/events/trigger` de Novu, con el email del asistente, el teléfono
de WhatsApp como `subscriberId`, y el resultado de la reserva en el
`payload`. El Workflow de Novu (`NOVU_WORKFLOW_ID`) es quien decide los
canales reales (email, SMS, push, in-app) — no se configuran acá.

### Configurar el webhook en Meta

En el dashboard de la app de Meta (WhatsApp → Configuration):

- **Callback URL**: `https://<tu-dominio-n8n>/webhook/whatsapp/webhook`
- **Verify token**: el mismo valor que pusiste en `WHATSAPP_VERIFY_TOKEN`
- Suscribir el campo `messages`.

### Pendiente / próximos pasos

- Responde de forma síncrona (Meta espera la respuesta del webhook antes
  de los ~20s de timeout); si la consulta RAG o Cal.com es lenta, conviene
  separar en "ack inmediato" + procesamiento asíncrono en un flujo aparte.
- **`Detect Intent` es por palabras clave**, no por un LLM — es un MVP.
  Frases ambiguas ("¿el jueves tenés lugar?") pueden no matchear ningún
  keyword y caer al camino `rag`, donde el RAG no sabrá responder sobre
  disponibilidad real. Mejora natural: reemplazar por una clasificación de
  intención vía LLM (mismo proveedor que ya usa `rag-service/`).
- **El agendado exige que el usuario escriba fecha/hora + email en un solo
  mensaje de texto**, con formato `AAAA-MM-DDTHH:MM`. No hay conversación
  guiada de varios turnos (pedir primero la fecha, después el email por
  separado) — WhatsApp no tiene estado de conversación en este workflow.
- `Book Cal.com Appointment` no verifica que el horario elegido siga
  disponible al momento de confirmar (puede haberse ocupado entre la
  consulta de disponibilidad y la confirmación); Cal.com devuelve error en
  ese caso y `Format Booking Confirmation` se lo reporta al usuario, pero no
  reintenta ni ofrece un horario alternativo automáticamente.
- `Trigger Novu Notification` asume que el Workflow de Novu
  (`NOVU_WORKFLOW_ID`) ya está creado y sus canales (email/SMS/etc.)
  configurados desde el dashboard de Novu — este repo no lo crea ni lo
  gestiona, solo dispara el evento.
- Si activás el workflow **antes** de configurar `WHATSAPP_APP_SECRET`, todo
  mensaje entrante quedará rechazado con `403` (falla cerrado, a propósito) —
  confirmar la variable en el `.env` antes de suscribir el webhook en Meta.
