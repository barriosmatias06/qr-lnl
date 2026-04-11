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
echo "[1/4] Docker..."
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
echo "[2/4] Repo..."
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
echo "[3/4] .env..."
if [ -f "$APP_DIR/.env" ] && grep -q "POSTGRES_PASSWORD" "$APP_DIR/.env"; then
    echo "  Reutilizando .env existente..."
    source "$APP_DIR/.env"
    DB_PASS="$POSTGRES_PASSWORD"
else
    DB_PASS=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 20)
    printf 'POSTGRES_DB=evento_db\nPOSTGRES_USER=evento\nPOSTGRES_PASSWORD=%s\nDOMAIN=%s\nACME_EMAIL=%s\n' "$DB_PASS" "$DOMAIN" "$EMAIL" > "$APP_DIR/.env"
fi
echo "  OK"

# ── 4. Deploy ─────────────────────────────────────────────────────
echo ""
echo "[4/4] Docker compose..."
cd "$APP_DIR"
docker compose down 2>/dev/null || true
mkdir -p traefik/letsencrypt
docker compose up -d --build

echo "  Esperando servicios..."
for i in $(seq 1 45); do
    if curl -skf "https://127.0.0.1:443/health" &>/dev/null; then
        echo "  OK HTTPS listo (${i}s)"
        break
    fi
    sleep 1
done

echo ""
echo "==============================="
echo "  DEPLOY COMPLETADO"
echo "==============================="
echo ""
echo "  Registro: https://${DOMAIN}/register"
echo "  Scanner:  https://${DOMAIN}"
echo ""
echo "  Comandos utiles:"
echo "    cd $APP_DIR"
echo "    docker compose logs -f traefik"
echo "    docker compose logs -f backend"
echo "    docker compose exec db psql -U evento -d evento_db"
echo ""
