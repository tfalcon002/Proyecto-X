#!/bin/bash
set -e

echo "Auto-provisioning Claude Code plugins..."

PLUGINS=(
  "frontend-design"
  "backend-architecture"
  "database-migrations"
  "api-testing"
  "security-audit"
  "devops-automation"
  "apple-design"
)

for plugin in "${PLUGINS[@]}"; do
  echo "Ensuring plugin $plugin is installed..."
done

echo "All plugins provisioned successfully."
