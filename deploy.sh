#!/bin/bash
set -e

DOMAIN="${1:?Uso: bash deploy.sh <dominio> <email>}"
EMAIL="${2:?Falta el email}"
APP_DIR="/opt/qr-lnl"
REPO_URL="https://github.com/barriosmatias06/qr-lnl.git"

echo "==============================="
echo "  Deploy QR - $DOMAIN"
echo "==============================="

# ── 1. Docker ──────────────────────────────────────────────────────
echo ""
echo "[1/8] Docker..."
if ! command -v docker &>/dev/null; then
    echo "  Instalando..."
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $CODENAME stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo "  OK instalado"
else
    echo "  OK $(docker --version)"
fi

if ! docker info &>/dev/null; then
    systemctl start docker
    sleep 3
fi

# ── 2. Repo ───────────────────────────────────────────────────────
echo ""
echo "[2/8] Repo..."
if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR"
    git stash 2>/dev/null || true
    git pull origin main
else
    rm -rf "$APP_DIR"
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# ── 3. .env ───────────────────────────────────────────────────────
echo ""
echo "[3/8] .env..."
if [ -f "$APP_DIR/.env" ] && grep -q "POSTGRES_PASSWORD" "$APP_DIR/.env"; then
    echo "  Reutilizando .env existente..."
    source "$APP_DIR/.env"
    DB_PASS="$POSTGRES_PASSWORD"
else
    DB_PASS=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 20)
    printf 'POSTGRES_DB=evento_db\nPOSTGRES_USER=evento\nPOSTGRES_PASSWORD=%s\nDOMAIN=%s\n' "$DB_PASS" "$DOMAIN" > "$APP_DIR/.env"
fi
echo "  OK"

# ── 4. SSL temp cert + nginx configs ──────────────────────────────
echo ""
echo "[4/8] SSL temp + nginx..."
mkdir -p "$APP_DIR/nginx/certbot/conf"
mkdir -p "$APP_DIR/nginx/certbot/www"

# Ensure self-signed certs exist before compose up
if [ ! -f "$APP_DIR/nginx/ssl-fullchain.pem" ]; then
    echo "  Generando certificado temporal..."
    openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
        -keyout "$APP_DIR/nginx/ssl-privkey.pem" \
        -out "$APP_DIR/nginx/ssl-fullchain.pem" \
        -subj "/CN=${DOMAIN}" 2>/dev/null
    echo "  OK cert generado"
fi

# ── 5. Start stack ────────────────────────────────────────────────
echo ""
echo "[5/7] Docker compose..."
cd "$APP_DIR"
docker compose down 2>/dev/null || true
docker compose up -d --build
echo "  Esperando backend..."

HEALTHY=false
for i in $(seq 1 45); do
    if curl -sf http://127.0.0.1:8000/health &>/dev/null; then
        HEALTHY=true
        echo "  OK backend listo (${i}s)"
        break
    fi
    sleep 1
done

if [ "$HEALTHY" != "true" ]; then
    echo "  ERROR backend no arranco:"
    docker compose logs backend 2>/dev/null | tail -30
    exit 1
fi

sleep 2
# Test HTTP
if curl -sf http://127.0.0.1:80/health &>/dev/null; then
    echo "  OK HTTP via nginx"
fi

# Test HTTPS (self-signed, -k to skip verify)
if curl -skf https://127.0.0.1:443/health &>/dev/null; then
    echo "  OK HTTPS via nginx (cert temporal)"
else
    echo "  WARN HTTPS no responde:"
    docker compose logs nginx 2>/dev/null | tail -10
fi

# ── 6. SSL Certificate ───────────────────────────────────────────
echo ""
echo "[6/7] Let's Encrypt SSL..."

# certbot container already running, just exec the command
docker compose run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    --force-renewal \
    -d "$DOMAIN"

echo "  Certificado real obtenido"

# Update ssl.conf to use real Let's Encrypt cert paths
sed "s/\${DOMAIN}/${DOMAIN}/g" "$APP_DIR/nginx/ssl.conf.template" > "$APP_DIR/nginx/ssl.conf"

# Update default.conf to redirect HTTP → HTTPS
cat > "$APP_DIR/nginx/default.conf" << 'REDIRECTEOF'
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
REDIRECTEOF

# Reload nginx to apply real cert + redirect
docker compose up -d --force-recreate nginx

echo ""
echo "  Verificando HTTPS real..."
sleep 3

if curl -skf https://127.0.0.1:443/health &>/dev/null; then
    echo "  OK HTTPS con Let's Encrypt"
fi

# Clean up temp certs
rm -f "$APP_DIR/nginx/ssl-privkey.pem" "$APP_DIR/nginx/ssl-fullchain.pem" 2>/dev/null

echo ""
echo "==============================="
echo "  Deploy QR - $DOMAIN"
echo "==============================="
echo ""
echo "  Registro: https://${DOMAIN}/register"
echo "  Scanner:  https://${DOMAIN}"
echo "==============================="
