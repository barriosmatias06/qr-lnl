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

# ── 4. QR generation ──────────────────────────────────────────────
echo ""
echo "[4/8] QRs..."
PYTHON=python3
if ! $PYTHON -c "import qrcode" &>/dev/null; then
    echo "  Instalando dependencias..."
    apt-get install -y -qq python3-pip python3-venv
    python3 -m venv "$APP_DIR/.venv"
    "$APP_DIR/.venv/bin/pip" install --quiet qrcode[pil] Pillow tqdm
    PYTHON="$APP_DIR/.venv/bin/python3"
fi
$PYTHON generate_qr.py --url "https://${DOMAIN}"
QR_COUNT=$(find qr_codes -name '*.png' 2>/dev/null | wc -l)
echo "  OK $QR_COUNT QRs"

# ── 5. Generate temporary self-signed cert + nginx configs ─────────
echo ""
echo "[5/8] SSL temp + nginx..."
mkdir -p "$APP_DIR/nginx/certbot/conf"
mkdir -p "$APP_DIR/nginx/certbot/www"

# Generate self-signed cert so nginx can listen on 443 from the start
echo "  Generando certificado temporal..."
openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
    -keyout "$APP_DIR/nginx/ssl-privkey.pem" \
    -out "$APP_DIR/nginx/ssl-fullchain.pem" \
    -subj "/CN=${DOMAIN}" 2>/dev/null

# Write nginx configs
# default.conf: HTTP proxy + acme-challenge + redirect to HTTPS
cat > "$APP_DIR/nginx/default.conf" << NGINXEOF
server {
    listen 80;
    server_name _;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass http://backend:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINXEOF

# ssl.conf: Uses self-signed cert initially, replaced after real cert
cat > "$APP_DIR/nginx/ssl.conf" << SLEOF
server {
    listen 443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate     /etc/nginx/ssl-temp/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl-temp/privkey.pem;

    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

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
SLEOF

echo "  OK certificados temporales + nginx configurado"

# ── 6. Start stack ────────────────────────────────────────────────
echo ""
echo "[6/8] Docker compose..."
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

# ── 7. Seed data ──────────────────────────────────────────────────
echo ""
echo "[7/8] Importando asistentes..."
sleep 5
SEED=$(curl -s -X POST http://127.0.0.1:8000/api/seed 2>/dev/null || echo "no disponible")
echo "  Seed: $SEED"

STATS=$(curl -s http://127.0.0.1:8000/api/stats 2>/dev/null || echo "no disponible")
echo "  Stats: $STATS"

# ── 8. Get real Let's Encrypt cert ────────────────────────────────
echo ""
echo "==============================="
echo "  Let's Encrypt SSL..."
echo "==============================="

docker compose up -d certbot
sleep 3

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
echo "  DEPLOY COMPLETADO"
echo "  https://${DOMAIN}"
echo "==============================="
echo ""
echo "  Comandos utiles:"
echo "    cd $APP_DIR"
echo "    docker compose logs -f backend"
echo "    docker compose logs -f nginx"
echo "    docker compose exec db psql -U evento -d evento_db"
echo ""
