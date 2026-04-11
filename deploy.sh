#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#  deploy.sh — Despliegue completo del sistema QR de acceso
#
#  Ejecutar en el servidor Ubuntu:
#    bash deploy.sh <tu-dominio.com> <tu@email.com>
#
#  Ejemplo:
#    bash deploy.sh evento.midominio.com admin@midominio.com
# ═══════════════════════════════════════════════════════════════════

set -e

DOMAIN="${1:?Uso: bash deploy.sh <dominio> <email>}"
EMAIL="${2:?Falta el email para Let's Encrypt}"

REPO_URL="https://github.com/barriosmatias06/qr-lnl.git"
APP_DIR="/opt/qr-lnl"
SEP="================================================"

echo "$SEP"
echo "  Deploy QR Access Control - $DOMAIN"
echo "$SEP"

# ── 1. Instalar Docker si no existe ───────────────────────────────
echo ""
echo "[1/7] Verificando Docker..."
if ! command -v docker &>/dev/null; then
    echo "   Docker no instalado. Instalando..."
    apt-get update
    apt-get install -y ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo "   OK Docker instalado"
else
    echo "   OK Docker: $(docker --version)"
fi

# Iniciar daemon si no corre
if ! docker info &>/dev/null; then
    echo "   Iniciando Docker daemon..."
    systemctl start docker
    sleep 3
fi

# ── 2. Clonar repo ───────────────────────────────────────────────
echo ""
echo "[2/7] Clonando repositorio..."
if [ -d "$APP_DIR" ]; then
    echo "   Directorio existe. Actualizando..."
    cd "$APP_DIR"
    git pull origin main
else
    mkdir -p "$(dirname "$APP_DIR")"
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi
echo "   OK Repo en $APP_DIR"

# ── 3. Configurar .env ───────────────────────────────────────────
echo ""
echo "[3/7] Configurando variables de entorno..."
cd "$APP_DIR"
DB_PASS=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 20)

cat > "$APP_DIR/.env" <<ENVEOF
POSTGRES_DB=evento_db
POSTGRES_USER=evento
POSTGRES_PASSWORD=${DB_PASS}
DOMAIN=${DOMAIN}
ENVEOF
echo "   OK .env creado"

# ── 4. Generar QRs ───────────────────────────────────────────────
echo ""
echo "[4/7] Generando codigos QR..."

if ! python3 -c "import qrcode" &>/dev/null; then
    echo "   Instalando dependencias Python..."
    pip3 install --quiet qrcode[pil] Pillow tqdm
fi

python3 generate_qr.py --url "https://${DOMAIN}"
QR_COUNT=$(find qr_codes -name "*.png" 2>/dev/null | wc -l)
echo "   OK $QR_COUNT imagenes QR generadas"

# ── 5. Preparar Nginx ────────────────────────────────────────────
echo ""
echo "[5/7] Preparando Nginx..."
mkdir -p "$APP_DIR/nginx/certbot/conf"
mkdir -p "$APP_DIR/nginx/certbot/www"

# Config HTTP temporal
cat > "$APP_DIR/nginx/default.conf" <<'NGINXEOF'
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
NGINXEOF

# Config SSL - escribir directamente con variables de Nginx
cat > "$APP_DIR/nginx/ssl.conf.template" <<TMPLEOF
server {
    listen 443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 30s;
        proxy_read_timeout    30s;
    }

    location /qr/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host \$host;
        proxy_cache_valid 200 60m;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://backend:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
TMPLEOF
echo "   OK Nginx configurado"

# ── 6. Levantar stack ────────────────────────────────────────────
echo ""
echo "[6/7] Levantando Docker Compose..."
docker compose down 2>/dev/null || true
docker compose up -d --build
echo "   OK Contenedores iniciados"
echo "   Esperando backend..."
sleep 10

if curl -sf http://127.0.0.1:8000/health &>/dev/null; then
    echo "   OK Backend respondiendo"
else
    echo "   WARNING Backend no responde aun. Ver: docker compose logs backend"
fi

# ── 7. Importar datos ────────────────────────────────────────────
echo ""
echo "[7/7] Importando asistentes..."
sleep 5
SEED_RESULT=$(curl -s -X POST http://127.0.0.1:8000/api/seed 2>/dev/null || echo "No disponible aun")
echo "   $SEED_RESULT"

STATS=$(curl -s http://127.0.0.1:8000/api/stats 2>/dev/null || echo "No disponible")
echo ""
echo "   Stats: $STATS"

# ── 8. Let's Encrypt ─────────────────────────────────────────────
echo ""
echo "$SEP"
echo "  Obteniendo certificado SSL..."
echo "$SEP"
echo ""

docker compose up -d nginx certbot
sleep 3

docker compose run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    --force-renewal \
    -d "$DOMAIN"

# Generar config SSL final (ya esta armada con el dominio)
cp "$APP_DIR/nginx/ssl.conf.template" "$APP_DIR/nginx/ssl.conf"

# Regenerar con SSL
docker compose up -d --force-recreate

echo ""
echo "$SEP"
echo "  DEPLOY COMPLETADO"
echo "$SEP"
echo ""
echo "  Tu app: https://${DOMAIN}"
echo "  Health:  https://${DOMAIN}/health"
echo "  Stats:   https://${DOMAIN}/api/stats"
echo ""
echo "  Comandos utiles:"
echo "    cd $APP_DIR"
echo "    docker compose logs -f backend"
echo "    docker compose restart backend"
echo "    docker compose exec db psql -U evento -d evento_db"
echo ""
echo "  Renovar SSL (cada 90 dias):"
echo "    docker compose run --rm certbot renew"
echo "    docker compose exec nginx nginx -s reload"
echo ""
echo "$SEP"
