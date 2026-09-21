#!/bin/bash
set -euo pipefail

# Solo corre en Claude Code on the web (contenedores efímeros): en local el
# usuario ya tiene sus plugins instalados de forma persistente.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "session-start: comando 'claude' no encontrado, se omite el aprovisionamiento de plugins." >&2
  exit 0
fi

MARKETPLACE="claude-plugins-official"
MARKETPLACE_SOURCE="anthropics/claude-plugins-official"
PLUGINS=(superpowers context7 frontend-design chrome-devtools-mcp neon exa github)

# Idempotente: agregar el marketplace solo si todavía no está registrado.
if ! claude plugin marketplace list 2>/dev/null | grep -q "$MARKETPLACE"; then
  echo "session-start: agregando marketplace $MARKETPLACE_SOURCE..."
  claude plugin marketplace add "$MARKETPLACE_SOURCE" || \
    echo "session-start: no se pudo agregar el marketplace (revisar salida de red)." >&2
fi

INSTALLED="$(claude plugin list 2>/dev/null || true)"

for plugin in "${PLUGINS[@]}"; do
  if echo "$INSTALLED" | grep -q "^  > ${plugin}@${MARKETPLACE}"; then
    echo "session-start: $plugin ya estaba instalado, se omite."
    continue
  fi
  echo "session-start: instalando ${plugin}@${MARKETPLACE}..."
  claude plugin install "${plugin}@${MARKETPLACE}" || \
    echo "session-start: fallo instalando $plugin (revisar salida de red / marketplace)." >&2
done

# neon, exa y github necesitan autorización (OAuth vía /mcp, o
# GITHUB_PERSONAL_ACCESS_TOKEN en el entorno) que no se puede automatizar
# acá — eso lo hace la persona en una sesión interactiva.
echo "session-start: plugins aprovisionados. neon/exa requieren '/mcp' para autorizar; github requiere GITHUB_PERSONAL_ACCESS_TOKEN en el entorno."
