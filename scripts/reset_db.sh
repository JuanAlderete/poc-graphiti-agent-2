#!/usr/bin/env bash
# =============================================================================
# scripts/reset_db.sh
# -------------------
# Resetea la base de datos cuando cambiás de proveedor LLM.
#
# CUÁNDO EJECUTAR:
#   Solo cuando cambias entre proveedores que tienen distintas dimensiones
#   de embedding (openai ↔ ollama/gemini).
#
#   openai  → text-embedding-3-small → 1536 dims
#   ollama  → nomic-embed-text       → 768 dims
#   gemini  → text-embedding-004     → 768 dims
#
# QUÉ HACE:
#   1. Muestra el proveedor actual en .env
#   2. Pide confirmación (DESTRUCTIVO)
#   3. Hace backup de los datos actuales (pg_dump)
#   4. Elimina las tablas
#   5. Las tablas se recrean automáticamente con las dims correctas
#      cuando la API arranca (DatabasePool.init_db())
#
# USO:
#   bash scripts/reset_db.sh
#
# PREREQUISITO: Docker corriendo con el servicio postgres activo
# =============================================================================

set -e

# Leer variables del .env
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

PROVIDER="${LLM_PROVIDER:-openai}"
PG_USER="${POSTGRES_USER:-marketingmaker}"
PG_DB="${POSTGRES_DB:-marketingmaker}"
PG_HOST="${POSTGRES_HOST:-localhost}"
PG_PORT="${POSTGRES_PORT:-5432}"
BACKUP_DIR="backups"

echo ""
echo "======================================================"
echo "  MARKETINGMAKER DB RESET"
echo "======================================================"
echo "  Proveedor:     $PROVIDER"
echo "  Base de datos: $PG_DB @ $PG_HOST:$PG_PORT"
echo ""

# Mostrar dims que corresponden
case "$PROVIDER" in
    openai)  DIMS=1536 ; MODEL="text-embedding-3-small" ;;
    ollama)  DIMS=768  ; MODEL="nomic-embed-text" ;;
    gemini)  DIMS=768  ; MODEL="text-embedding-004" ;;
    *)       echo "ERROR: LLM_PROVIDER='$PROVIDER' no reconocido." ; exit 1 ;;
esac

echo "  La nueva tabla chunks tendrá: vector($DIMS) [$MODEL]"
echo ""
echo "  ⚠️  ATENCIÓN: Esto elimina TODOS los datos de Postgres."
echo "  Los documentos deberán re-ingestionarse."
echo ""
read -p "¿Continuar? [y/N] " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelado."
    exit 0
fi

# Backup
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/backup_$(date +%Y%m%d_%H%M%S)_before_${PROVIDER}_reset.sql"
echo ""
echo "📦 Haciendo backup en $BACKUP_FILE ..."

if docker ps --format '{{.Names}}' | grep -q "marketingmaker_postgres"; then
    docker exec marketingmaker_postgres pg_dump \
        -U "$PG_USER" \
        -d "$PG_DB" \
        --no-owner \
        --no-acl \
        -f "/tmp/backup.sql" 2>/dev/null || true

    docker cp marketingmaker_postgres:/tmp/backup.sql "$BACKUP_FILE" 2>/dev/null || true
    echo "✅ Backup guardado en $BACKUP_FILE"
else
    echo "⚠️  Postgres no está corriendo en Docker. Saltando backup."
fi

# Drop tables
echo ""
echo "🗑️  Eliminando tablas..."

PSQL_CMD="docker exec -e PGPASSWORD=$POSTGRES_PASSWORD marketingmaker_postgres psql -U $PG_USER -d $PG_DB"

$PSQL_CMD -c "
    DROP TABLE IF EXISTS token_usage CASCADE;
    DROP TABLE IF EXISTS generated_content CASCADE;
    DROP TABLE IF EXISTS weekly_runs CASCADE;
    DROP TABLE IF EXISTS chunks CASCADE;
    DROP TABLE IF EXISTS documents CASCADE;
" 2>/dev/null || \
psql -U "$PG_USER" -h "$PG_HOST" -p "$PG_PORT" -d "$PG_DB" -c "
    DROP TABLE IF EXISTS token_usage CASCADE;
    DROP TABLE IF EXISTS generated_content CASCADE;
    DROP TABLE IF EXISTS weekly_runs CASCADE;
    DROP TABLE IF EXISTS chunks CASCADE;
    DROP TABLE IF EXISTS documents CASCADE;
"

echo ""
echo "✅ Tablas eliminadas."
echo ""
echo "📋 Próximos pasos:"
echo "   1. Asegurarte de que .env tiene LLM_PROVIDER=$PROVIDER"
if [ "$PROVIDER" = "ollama" ]; then
echo "   2. Levantar Ollama: docker compose --profile local up -d"
echo "   3. Descargar modelos:"
echo "      docker exec marketingmaker_ollama ollama pull llama3.1:8b"
echo "      docker exec marketingmaker_ollama ollama pull nomic-embed-text"
echo "   4. Levantar API:    docker compose up -d api"
else
echo "   2. Levantar servicios: docker compose up -d"
fi
echo "   5. Las tablas se recrean automáticamente con vector($DIMS) al arrancar la API."
echo "   6. Re-ingestar documentos: POST /ingest"
echo ""