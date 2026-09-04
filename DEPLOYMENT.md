# Despliegue en VPS con Coolify — Fase 4

Runbook paso a paso para llevar el stack local (`docker-compose.yml`:
n8n + Postgres/pgvector + rag-service) a un VPS de producción usando
Coolify como capa de despliegue y reverse proxy. Ejecutar en orden.

Requisitos previos (ver también `INFRAESTRUCTURA.md`): VPS Linux
(Ubuntu 22.04/24.04) con mínimo 2 vCPU / 4 GB RAM, 40 GB+ disco, acceso
root por SSH, y un dominio (o subdominios) que puedas apuntar al VPS.

## 1. Provisionar el VPS y apuntar el DNS

1. Levantar el VPS (cualquier proveedor: Hetzner, DigitalOcean, etc.)
   con Ubuntu 22.04/24.04 y anotar su IP pública.
2. En tu proveedor de DNS, crear un registro **A** apuntando a esa IP:
   - `n8n.tudominio.com` → IP del VPS (obligatorio: es el endpoint que
     recibe los webhooks de Meta).
   - Opcional: `coolify.tudominio.com` si querés acceder al panel de
     Coolify con dominio propio en vez de `IP:8000`.
   - **No** hace falta un subdominio para `rag`: el servicio RAG solo
     lo llama `n8n` internamente (`http://rag:8000`), nunca se expone
     a internet.
3. Esperar a que el DNS propague (`dig n8n.tudominio.com` debe devolver
   la IP del VPS) antes de pedirle un certificado TLS a Coolify — si no
   propagó, Let's Encrypt falla.

## 2. Instalar Coolify

Por SSH, como root:

```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
```

Al terminar, el instalador muestra la URL del panel
(`http://<IP-del-VPS>:8000`). Entrar, crear el usuario admin, y en
**Settings → Instance** configurar `coolify.tudominio.com` si querés
un dominio propio para el panel (opcional).

## 3. Conectar el repositorio

1. En Coolify: **Sources → Add a new source → GitHub App** (o "Public
   repository" si preferís no dar permisos de escritura — este repo es
   público, así que alcanza con la opción pública/deploy-key-only).
2. Crear un **Project** (ej. "Falcon") y dentro un **Resource** de tipo
   **Docker Compose**, apuntando a este repo, branch `main`, archivo
   `docker-compose.yml` en la raíz.

## 4. Variables de entorno de producción

En la pestaña **Environment Variables** del resource, cargar todas las
claves de `.env.example` con valores **reales de producción** (nunca
los del ejemplo). Puntos que cambian respecto a local:

| Variable | Valor en producción |
|---|---|
| `N8N_HOST` | `n8n.tudominio.com` |
| `N8N_PROTOCOL` | `https` |
| `WEBHOOK_URL` | `https://n8n.tudominio.com/` |
| `POSTGRES_PASSWORD`, `N8N_BASIC_AUTH_PASSWORD`, `RAG_API_KEY`, `WHATSAPP_VERIFY_TOKEN` | Generar valores nuevos y fuertes — nunca reutilizar los de `.env.example` ni los de tu `.env` local |
| `N8N_ENCRYPTION_KEY` | Generar una vez con `openssl rand -hex 32` y **no volver a tocarla** tras el primer arranque (perdés las credenciales guardadas en n8n si cambia) |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Los reales de tu app de Meta (ver `workflows/README.md`) |
| `OPENAI_API_KEY` (o `OLLAMA_*` si vas con proveedor local) | Clave real |

El resto de las variables (`POSTGRES_USER`, `POSTGRES_DB`, `RAG_DB`,
`EMBEDDING_*`, `LLM_PROVIDER`, etc.) pueden quedar iguales a
`.env.example`, solo revisando que `EMBEDDING_DIM` coincida con el
modelo elegido.

No es necesario declarar `SERVICE_FQDN_*` de Coolify: el dominio de
`n8n` se asigna en el paso 5 directamente sobre el servicio.

## 5. Exponer solo `n8n` a internet

En **Configuration → Domains** del resource, asignar
`https://n8n.tudominio.com` únicamente al servicio `n8n` (puerto
interno `5678`). Confirmar que **ningún** dominio quede asignado a
`postgres` ni a `rag` — deben ser alcanzables solo dentro de la red
interna de Docker que Coolify crea para el stack, nunca desde afuera.

Coolify gestiona el certificado TLS (Let's Encrypt) automáticamente
sobre ese dominio una vez que el DNS resuelve.

## 6. Deploy

1. Botón **Deploy** en el resource. Coolify hace `git pull` +
   `docker compose up -d --build` en el VPS.
2. Revisar logs de build/arranque desde la misma UI. Confirmar que los
   tres contenedores (`postgres`, `n8n`, `rag`) queden `healthy`/
   `running` (mismo chequeo que `docker compose ps` en local, ver
   `INFRAESTRUCTURA.md`).
3. Entrar a `https://n8n.tudominio.com` y loguear con
   `N8N_BASIC_AUTH_USER`/`N8N_BASIC_AUTH_PASSWORD`.

## 7. Importar el workflow y activar el webhook de Meta

1. Dentro de n8n, importar `workflows/whatsapp-rag-inbound.json` (ver
   pasos exactos en `workflows/README.md`).
2. **Activar** el workflow (toggle arriba a la derecha) — con el
   workflow inactivo, n8n no atiende el webhook.
3. En el dashboard de Meta for Developers, configurar el webhook de
   WhatsApp con:
   - **Callback URL**: `https://n8n.tudominio.com/webhook/whatsapp/webhook`
   - **Verify token**: el mismo valor que `WHATSAPP_VERIFY_TOKEN`
   Meta hace un `GET` de verificación inmediatamente al guardar — si
   el nodo de verificación del workflow responde bien, queda
   confirmado en el panel de Meta.
4. Probar de punta a punta: mandar un mensaje de WhatsApp al número
   configurado y confirmar que llega la respuesta generada por el RAG.

## 8. Backups

El volumen `postgres_data` contiene **todo**: credenciales de n8n,
historial de ejecuciones, y los documentos indexados del RAG
(`falcon_documents` en la base `RAG_DB`). Configurar uno de:

- **Backups nativos de Coolify** (Storage → Backups) apuntando al
  volumen de `postgres`, con retención diaria/semanal.
- O un cron propio en el VPS con `pg_dump` hacia almacenamiento externo
  (S3, etc.) si preferís no depender del backup interno de Coolify.

Probar al menos una restauración antes de confiar en el esquema
elegido — un backup nunca probado no cuenta como backup.

## 9. Actualizaciones futuras

Cada push a `main` que toque `docker-compose.yml`, `rag-service/`, o
cualquier archivo del stack requiere un nuevo **Deploy** manual (o
activar **Auto Deploy** en el resource para que Coolify redepliegue
solo en cada push). `N8N_ENCRYPTION_KEY` y los datos en los volúmenes
persisten entre deploys mientras no se borren los volúmenes ni cambie
esa clave.

## Checklist final

- [ ] DNS de `n8n.tudominio.com` resuelve a la IP del VPS
- [ ] Coolify instalado y accesible
- [ ] Resource Docker Compose creado, apuntando a `main`
- [ ] Variables de entorno de producción cargadas (passwords nuevos,
      `N8N_ENCRYPTION_KEY` generada una sola vez)
- [ ] Dominio HTTPS asignado solo a `n8n`; `postgres`/`rag` sin dominio
- [ ] Deploy exitoso, los 3 contenedores `healthy`/`running`
- [ ] Workflow importado y **activado** en n8n
- [ ] Webhook de Meta verificado con la callback URL de producción
- [ ] Prueba end-to-end: mensaje de WhatsApp → respuesta del RAG
- [ ] Backup del volumen de Postgres configurado y probado
