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
DB_PASS=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 20)
printf 'POSTGRES_DB=evento_db\nPOSTGRES_USER=evento\nPOSTGRES_PASSWORD=%s\nDOMAIN=%s\n' "$DB_PASS" "$DOMAIN" > "$APP_DIR/.env"
echo "  OK"

# ── 4. QR generation ──────────────────────────────────────────────
echo ""
echo "[4/8] QRs..."
if ! python3 -c "import qrcode" &>/dev/null; then
    echo "  Instalando dependencias..."
    apt-get install -y -qq python3-pip python3-venv
    python3 -m venv "$APP_DIR/.venv"
    "$APP_DIR/.venv/bin/pip" install --quiet qrcode[pil] Pillow tqdm
fi
python3 generate_qr.py --url "https://${DOMAIN}"
QR_COUNT=$(find qr_codes -name '*.png' 2>/dev/null | wc -l)
echo "  OK $QR_COUNT QRs"

# ── 5. Nginx configs ──────────────────────────────────────────────
echo ""
echo "[5/8] Nginx configs..."
mkdir -p "$APP_DIR/nginx/certbot/conf"
mkdir -p "$APP_DIR/nginx/certbot/www"

# Create empty ssl.conf so Docker mounts a file not a directory
touch "$APP_DIR/nginx/ssl.conf"

# default.conf stays as-is from repo (HTTP-only with redirect)
echo "  OK"

# ── 6. Start stack (HTTP only, no SSL yet) ────────────────────────
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
        echo "  OK backend listo ($i/s)"
        break
    fi
    sleep 1
done

if [ "$HEALTHY" != "true" ]; then
    echo "  ERROR backend no arranco. Logs:"
    docker compose logs backend 2>/dev/null | tail -20
    echo "  Intentando continuar..."
fi

# ── 7. Seed data ──────────────────────────────────────────────────
echo ""
echo "[7/8] Importando asistentes..."
SEED=$(curl -s -X POST http://127.0.0.1:8000/api/seed 2>/dev/null || echo "no disponible")
echo "  $SEED"

STATS=$(curl -s http://127.0.0.1:8000/api/stats 2>/dev/null || echo "no disponible")
echo "  $STATS"

# ── 8. SSL Certificate ───────────────────────────────────────────
echo ""
echo "==============================="
echo "  SSL Certificate..."
echo "==============================="

# Ensure nginx + certbot are up
docker compose up -d nginx certbot
sleep 5

# Obtain cert
docker compose run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    --force-renewal \
    -d "$DOMAIN"

echo "  Certificado obtenido"

# Generate real ssl.conf from template
sed "s/\${DOMAIN}/${DOMAIN}/g" "$APP_DIR/nginx/ssl.conf.template" > "$APP_DIR/nginx/ssl.conf"

# Restart nginx to pick up SSL
docker compose up -d --force-recreate nginx backend

echo ""
echo "==============================="
echo "  DEPLOY COMPLETADO"
echo "  https://${DOMAIN}"
echo "==============================="
echo ""
echo "  Comandos utiles:"
echo "    cd $APP_DIR"
echo "    docker compose logs -f backend"
echo "    docker compose exec db psql -U evento -d evento_db"
echo ""
