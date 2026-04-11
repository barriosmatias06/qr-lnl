#!/bin/bash
# seed.sh — Importar asistentes desde CSV al backend corriendo en Docker
#
# Uso:
#   bash seed.sh                    # Usa asistentes_import.csv por defecto
#   bash seed.sh otro_archivo.csv   # Usa un CSV específico
#

set -e

CSV_FILE="${1:-asistentes_import.csv}"
DOMAIN="${2:-}"  # Opcional: tu dominio, ej: https://evento.midominio.com

if [ ! -f "$CSV_FILE" ]; then
    echo "❌ Error: Archivo '$CSV_FILE' no encontrado."
    echo "   Generarlo primero con: python generate_qr.py --input tus_datos.csv"
    exit 1
fi

echo "══════════════════════════════════════════════════════"
echo "  Seed de Asistentes — $CSV_FILE"
echo "══════════════════════════════════════════════════════"

# Verificar que el backend esté corriendo
if ! docker compose ps backend | grep -q "Up"; then
    echo ""
    echo "⚠️  El backend no está corriendo. Levantándolo..."
    docker compose up -d backend
    sleep 5
fi

# Copiar CSV al contenedor
echo ""
echo "📂 Copiando CSV al contenedor..."
docker compose cp "$CSV_FILE" backend:/app/data/asistentes_import.csv

# Ejecutar seed
echo ""
echo "🌱 Ejecutando seed..."
if [ -n "$DOMAIN" ]; then
    # Si se proporciona dominio, usar la URL pública
    RESPONSE=$(curl -s -X POST "${DOMAIN}/api/seed")
else
    # Si no, usar directamente el contenedor
    RESPONSE=$(docker compose exec -T backend python -c "
import asyncio
import sys
sys.path.insert(0, '/app')
from app.seed import seed_from_csv
from app.database import async_session

async def main():
    async with async_session() as session:
        count = await seed_from_csv(session)
        print(f'✅ {count} asistentes importados correctamente.')

asyncio.run(main())
")
fi

echo ""
echo "$RESPONSE"

# Verificar stats
echo ""
echo "📊 Estadísticas actuales:"
if [ -n "$DOMAIN" ]; then
    curl -s "${DOMAIN}/api/stats" | python3 -m json.tool 2>/dev/null || curl -s "${DOMAIN}/api/stats"
else
    curl -s http://localhost:8000/api/stats | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8000/api/stats
fi

echo ""
echo "══════════════════════════════════════════════════════"
echo "  ✅ Seed completado"
echo "══════════════════════════════════════════════════════"
