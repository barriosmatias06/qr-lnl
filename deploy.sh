#!/bin/bash
set -e

DOMAIN="${1:?Uso: bash deploy.sh <dominio> <email>}"
EMAIL="${2:?Falta el email}"
APP_DIR="/opt/qr-lnl"
REPO_URL="https://github.com/barriosmatias06/qr-lnl.git"

echo "==============================="
echo "  Deploy QR - $DOMAIN"
echo "==============================="

# 1 Docker
echo "[1/7] Docker..."
if ! command -v docker &>/dev/null; then
    apt-get update
    apt-get install -y ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    CODENAME=$(lsb_release -cs)
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $CODENAME stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo "  OK Docker instalado"
else
    echo "  OK $(docker --version)"
fi

if ! docker info &>/dev/null; then
    systemctl start docker
    sleep 3
fi

# 2 Repo
echo "[2/7] Repo..."
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR"
    git pull origin main
else
    mkdir -p "$(dirname "$APP_DIR")"
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# 3 .env
echo "[3/7] .env..."
DB_PASS=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 20)
echo "POSTGRES_DB=evento_db" > "$APP_DIR/.env"
echo "POSTGRES_USER=evento" >> "$APP_DIR/.env"
echo "POSTGRES_PASSWORD=${DB_PASS}" >> "$APP_DIR/.env"
echo "DOMAIN=${DOMAIN}" >> "$APP_DIR/.env"
echo "  OK"

# 4 QRs
echo "[4/7] QRs..."
if ! python3 -c "import qrcode" &>/dev/null; then
    apt-get install -y python3-pip
    pip3 install --break-system-packages --quiet qrcode[pil] Pillow tqdm 2>/dev/null || \
    python3 -m pip install --break-system-packages --quiet qrcode[pil] Pillow tqdm
fi
python3 generate_qr.py --url "https://${DOMAIN}"
echo "  OK $(find qr_codes -name '*.png' | wc -l) QRs"

# 5 Nginx configs from repo + sed
echo "[5/7] Nginx..."
mkdir -p "$APP_DIR/nginx/certbot/conf" "$APP_DIR/nginx/certbot/www"

# Generate SSL config from template using sed
sed "s/\${DOMAIN}/${DOMAIN}/g" "$APP_DIR/nginx/ssl.conf.template" > "$APP_DIR/nginx/ssl.conf"
echo "  OK ssl.conf generado"

# 6 Start stack
echo "[6/7] Docker compose..."
cd "$APP_DIR"
docker compose down 2>/dev/null || true
docker compose up -d --build
sleep 10

if curl -sf http://127.0.0.1:8000/health &>/dev/null; then
    echo "  OK backend up"
else
    echo "  WARN: docker compose logs backend"
fi

sleep 5
echo "  Seed:"
curl -s -X POST http://127.0.0.1:8000/api/seed 2>/dev/null || echo "  (pending)"
echo ""
curl -s http://127.0.0.1:8000/api/stats 2>/dev/null || echo "  (pending)"

# 7 SSL
echo ""
echo "==============================="
echo "  SSL Cert..."
echo "==============================="
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

docker compose up -d --force-recreate

echo ""
echo "==============================="
echo "  DONE - https://${DOMAIN}"
echo "==============================="
