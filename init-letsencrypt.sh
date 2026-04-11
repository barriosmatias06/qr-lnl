#!/bin/bash
# init-letsencrypt.sh — Script para obtener certificados SSL con Certbot
#
# Uso:
#   1. Editar la variable DOMAIN en este archivo
#   2. Ejecutar: bash init-letsencrypt.sh
#   3. El script levanta nginx, obtiene certs, y regenera la config con SSL

set -e

# ═══════════════════════════════════════════════════════════════════
# CONFIGURACIÓN — MODIFICAR ANTES DE EJECUTAR
# ═══════════════════════════════════════════════════════════════════
DOMAIN="tu-dominio.com"          # ← Tu dominio (debe apuntar al servidor)
EMAIL="tu@email.com"             # ← Email para Let's Encrypt (notificaciones de renovación)
# ═══════════════════════════════════════════════════════════════════

if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "tu-dominio.com" ]; then
    echo "ERROR: Debes editar DOMAIN y EMAIL en este script antes de ejecutarlo."
    exit 1
fi

echo "══════════════════════════════════════════════════════"
echo "  Let's Encrypt Setup — $DOMAIN"
echo "══════════════════════════════════════════════════════"

# 1. Crear directorios necesarios
mkdir -p nginx/certbot/conf
mkdir -p nginx/certbot/www

# 2. Levantar solo nginx + certbot (sin backend/db) con config HTTP-only
echo ""
echo "📦 Levantando Nginx para validación HTTP..."
docker compose up -d nginx certbot

# 3. Obtener certificado (primera vez)
echo ""
echo "🔐 Solicitando certificado SSL para $DOMAIN ..."
docker compose run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    --force-renewal \
    -d "$DOMAIN"

echo "✅ Certificado obtenido!"

# 4. Generar la configuración SSL desde el template
echo ""
echo "⚙️  Generando configuración SSL de Nginx..."
sed "s/\${DOMAIN}/$DOMAIN/g" nginx/ssl.conf.template > nginx/ssl.conf

# 5. Comentar la config default y activar SSL
echo ""
echo "🔄 Reconfigurando Nginx con SSL..."
# Backup de la config actual
cp nginx/default.conf nginx/default.conf.bak 2>/dev/null || true

# Reemplazar default.conf para que no haga redirect (certbot ya tiene el cert)
cat > nginx/default.conf << 'EOF'
# Esta config se reemplaza automáticamente después de obtener certs
# Ver nginx/ssl.conf para la config SSL final
server {
    listen 80;
    server_name _;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        return 301 https://$host$request_uri;
    }
}
EOF

# 6. Levantar todo el stack
echo ""
echo "🚀 Levantando todo el stack..."
docker compose up -d --force-recreate

echo ""
echo "══════════════════════════════════════════════════════"
echo "  ✅ ¡LISTO! Tu app está en https://$DOMAIN"
echo "══════════════════════════════════════════════════════"
echo ""
echo "  📝 Para renovar certificados (cada 90 días):"
echo "     docker compose run --rm certbot renew"
echo ""
echo "  📝 O agregar al crontab:"
echo "     0 3 * * * cd /ruta/qr-lnl && docker compose run --rm certbot renew --quiet && docker compose exec nginx nginx -s reload"
echo ""
