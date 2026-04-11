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

# ── Parámetros ─────────────────────────────────────────────────────
DOMAIN="${1:?Uso: bash deploy.sh <dominio> <email>}"
EMAIL="${2:?Falta el email para Let's Encrypt}"

REPO_URL="https://github.com/barriosmatias06/qr-lnl.git"
APP_DIR="/opt/qr-lnl"
SEPARATOR="══════════════════════════════════════════════════════"

echo "$SEPARATOR"
echo "  Deploy QR Access Control — $DOMAIN"
echo "$SEPARATOR"

# ── 1. Instalar Docker si no existe ───────────────────────────────
echo ""
echo "📦 [1/7] Verificando Docker..."
if ! command -v docker &>/dev/null; then
    echo "   Docker no instalado. Instalando..."
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo systemctl enable docker
    sudo systemctl start docker
    sudo usermod -aG docker "$USER"
    echo "   ✅ Docker instalado"
else
    echo "   ✅ Docker ya está: $(docker --version)"
fi

# Verificar compose
if ! docker compose version &>/dev/null; then
    echo "   ⚠️  Docker Compose no detectado. Reinstalar Docker."
    exit 1
fi

# Iniciar daemon si no corre
if ! docker info &>/dev/null; then
    echo "   ⚙️  Iniciando Docker daemon..."
    sudo systemctl start docker 2>/dev/null || sudo dockerd &
    sleep 3
fi

# ── 2. Clonar repo ───────────────────────────────────────────────
echo ""
echo "📂 [2/7] Clonando repositorio..."
if [ -d "$APP_DIR" ]; then
    echo "   Directorio existe. Actualizando..."
    cd "$APP_DIR"
    git pull origin main
else
    sudo mkdir -p "$(dirname "$APP_DIR")"
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
    sudo chown -R "$USER:$USER" "$APP_DIR"
fi
echo "   ✅ Repo clonado en $APP_DIR"

# ── 3. Configurar .env ───────────────────────────────────────────
echo ""
echo "⚙️  [3/7] Configurando variables de entorno..."
DB_PASS=$(openssl rand -base64 16 2>/dev/null || head /dev/urandom | tr -dc A-Za-z0-9 | head -c 20)

cat > "$APP_DIR/.env" << EOF
POSTGRES_DB=evento_db
POSTGRES_USER=evento
POSTGRES_PASSWORD=${DB_PASS}
DOMAIN=${DOMAIN}
EOF
echo "   ✅ .env creado (DB pass generado aleatoriamente)"

# ── 4. Generar QRs ───────────────────────────────────────────────
echo ""
echo "🔑 [4/7] Generando códigos QR..."
cd "$APP_DIR"

# Instalar deps Python si no existen
if ! python3 -c "import qrcode" &>/dev/null; then
    echo "   Instalando dependencias Python..."
    pip3 install --quiet qrcode[pil] Pillow tqdm 2>/dev/null || pip3 install --quiet --user qrcode[pil] Pillow tqdm
fi

# Generar con datos de muestra (1800 asistentes)
python3 generate_qr.py --url "https://${DOMAIN}"
echo "   ✅ $(ls qr_codes/*.png 2>/dev/null | wc -l) imágenes QR generadas"

# ── 5. Preparar Nginx ────────────────────────────────────────────
echo ""
echo "🌐 [5/7] Preparando Nginx..."
mkdir -p "$APP_DIR/nginx/certbot/conf"
mkdir -p "$APP_DIR/nginx/certbot/www"

# Config HTTP temporal (antes de tener certs)
cat > "$APP_DIR/nginx/default.conf" << 'NGINX'
server {
    listen 80;
    server_name _;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    # No redirect yet — need cert first
    location / {
        return 301 https://$host$request_uri;
    }
}
NGINX

# Template SSL
cat > "$APP_DIR/nginx/ssl.conf.template" << EOF
server {
    listen 443 ssl http2;
    server_name \${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/\${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/\${DOMAIN}/privkey.pem;

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
EOF
echo "   ✅ Nginx configurado"

# ── 6. Levantar stack ────────────────────────────────────────────
echo ""
echo "🚀 [6/7] Levantando Docker Compose..."
cd "$APP_DIR"
docker compose down 2>/dev/null || true
docker compose up -d --build
echo "   ✅ Contenedores iniciados"
echo "   Esperando que el backend esté listo..."
sleep 10

# Verificar
if curl -sf http://localhost:80/health &>/dev/null; then
    echo "   ✅ Backend respondiendo"
else
    echo "   ⚠️  Backend no responde aún. Ver logs: docker compose logs backend"
fi

# ── 7. Importar datos ────────────────────────────────────────────
echo ""
echo "🌱 [7/7] Importando asistentes a la base de datos..."
sleep 5
SEED_RESULT=$(curl -s -X POST "http://localhost:8000/api/seed" -H "Host: ${DOMAIN}" 2>/dev/null || echo "No disponible aún")
echo "   $SEED_RESULT"

# Stats
STATS=$(curl -s "http://localhost:8000/api/stats" -H "Host: ${DOMAIN}" 2>/dev/null || echo "No disponible")
echo ""
echo "   📊 Estadísticas: $STATS"

# ── 8. Let's Encrypt ─────────────────────────────────────────────
echo ""
echo "$SEPARATOR"
echo "  🔐 Obteniendo certificado SSL..."
echo "$SEPARATOR"
echo ""

# Levantar nginx + certbot para validación
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

# Generar config SSL final
sed "s/\${DOMAIN}/$DOMAIN/g" "$APP_DIR/nginx/ssl.conf.template" > "$APP_DIR/nginx/ssl.conf"

# Regenerar con todo
docker compose up -d --force-recreate

echo ""
echo "$SEPARATOR"
echo "  ✅ ¡DEPLOY COMPLETADO!"
echo "$SEPARATOR"
echo ""
echo "  🌐 Tu app: https://${DOMAIN}"
echo "  📊 Health:  https://${DOMAIN}/health"
echo "  📈 Stats:   https://${DOMAIN}/api/stats"
echo ""
echo "  📝 Comandos útiles:"
echo "     cd $APP_DIR"
echo "     docker compose logs -f backend     # Ver logs"
echo "     docker compose restart backend     # Reiniciar backend"
echo "     docker compose exec db psql -U evento -d evento_db  # Acceder a DB"
echo ""
echo "  🔄 Renovar SSL (cada 90 días):"
echo "     docker compose run --rm certbot renew"
echo "     docker compose exec nginx nginx -s reload"
echo ""
echo "$SEPARATOR"
