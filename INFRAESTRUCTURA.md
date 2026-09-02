# Infraestructura Falcon — Fase 1 (Base)

Documento vivo de la infraestructura de automatización de Falcon. Esta fase
cubre solo el núcleo: **n8n + Postgres**, corriendo en local con Docker
Compose, como paso previo a desplegar en un VPS con Coolify.

## Qué levanta este repo hoy

- `docker-compose.yml`: dos servicios — `postgres` (persistencia de n8n) y
  `n8n` (motor de workflows).
- `.env.example`: variables necesarias, sin valores reales.

Todavía **no** incluye: Ollama/vLLM, base vectorial para RAG, ni el reverse
proxy — eso entra en fases siguientes (ver "Próximos pasos").

## Requisitos para correr local

- Docker y Docker Compose (`docker compose version` ≥ v2).
- Puerto `5678` libre (o cambiar `N8N_PORT` en `.env`).

## Variables de entorno

Copiar `.env.example` a `.env` y completar:

| Variable | Uso | Nota |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Credenciales de la base de datos de n8n | Cambiar el password por defecto siempre |
| `N8N_ENCRYPTION_KEY` | Cifra las credenciales guardadas dentro de n8n | Generar con `openssl rand -hex 32`. **No cambiar una vez en uso** — se pierden las credenciales guardadas |
| `N8N_HOST` | Host donde vive n8n | `localhost` en local, dominio real en VPS |
| `N8N_PROTOCOL` | `http` en local, `https` en VPS | |
| `WEBHOOK_URL` | URL pública que reciben los webhooks (Meta, etc.) | Debe ser accesible desde internet en producción |
| `N8N_PORT` | Puerto expuesto | Default `5678` |
| `GENERIC_TIMEZONE` | Zona horaria para triggers programados | Ej. `America/Mexico_City` |
| `N8N_BASIC_AUTH_USER` / `N8N_BASIC_AUTH_PASSWORD` | Login básico al panel de n8n | Obligatorio si se expone a internet |

## Probar en local

```bash
cp .env.example .env
# editar .env con valores propios (mínimo: contraseñas y N8N_ENCRYPTION_KEY)
docker compose up -d
docker compose ps        # confirmar que postgres y n8n están "healthy"/"running"
```

n8n queda disponible en `http://localhost:5678` (pide el usuario/clave de
`N8N_BASIC_AUTH_USER`/`N8N_BASIC_AUTH_PASSWORD`).

Para bajar el entorno sin perder datos: `docker compose down`.
Para bajarlo y borrar todo (empezar de cero): `docker compose down -v`.

## Requisitos del VPS (fase de despliegue, aún no ejecutada)

- **CPU/RAM**: mínimo 2 vCPU / 4 GB RAM para n8n + Postgres. Si se suma
  Ollama con modelos locales, subir a 8 GB+ RAM (16 GB+ si el modelo es
  grande) y considerar GPU.
- **Disco**: 40 GB+ (crece con el historial de ejecuciones de n8n y los
  datos de Postgres).
- **SO**: Linux (Ubuntu 22.04/24.04 recomendado), con Docker instalado.
- **Coolify**: instalado sobre ese mismo VPS como capa de despliegue y
  reverse proxy (gestiona TLS automático vía Let's Encrypt).
- **Dominio**: un subdominio apuntando al VPS (ej. `n8n.falcon.com`) para
  que `N8N_HOST`/`WEBHOOK_URL` sean públicos y estables — obligatorio para
  que Meta (WhatsApp/Instagram Cloud API) pueda entregar webhooks.
- **Puertos**: 80/443 abiertos (los gestiona Coolify); no exponer 5678 ni
  5432 directo a internet — todo el tráfico externo entra por el reverse
  proxy de Coolify con TLS.
- **Backups**: snapshot periódico del volumen de Postgres (contiene todas
  las credenciales y el historial de workflows).

## Próximos pasos

1. Validar este entorno local (`docker compose up`) y confirmar que n8n
   arranca y guarda un workflow de prueba tras un reinicio del contenedor.
2. Fase 2: agregar el primer workflow real (webhook de WhatsApp/Meta →
   n8n) y decidir si el LLM corre local (Ollama) o vía API.
3. Fase 3: aprovisionar el VPS, instalar Coolify, y migrar este mismo
   `docker-compose.yml` (con `.env` de producción) detrás de su reverse
   proxy.
