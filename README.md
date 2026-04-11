# 🎫 Control de Acceso QR — Evento

Sistema de control de acceso para eventos con generación de códigos QR únicos, escaneo por cámara y registro de asistencia en tiempo real.

**Stack**: FastAPI + PostgreSQL + Nginx + Let's Encrypt + Docker Compose

---

## 📋 Arquitectura

```
┌──────────────────────────────────────────────────────┐
│  Nginx (Reverse Proxy + SSL)                         │
│  Puertos: 80, 443                                    │
├──────────────────┬───────────────────────────────────┤
│                  │                                   │
│  /api/*    ──────┼──► Backend FastAPI (Python 3.12)  │
│  /qr/*     ──────┤    Puertos: 8000 (interno)        │
│  /*        ──────┼──► Frontend (SPA HTML)             │
│                  │                                   │
├──────────────────┴───────────────────────────────────┤
│  PostgreSQL 16 (Alpine)                              │
│  Puerto: 5432                                        │
└──────────────────────────────────────────────────────┘
```

### Endpoints del Backend

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/check?hash=XXX` | Validar QR y registrar asistencia |
| `GET` | `/api/stats` | Estadísticas (total, ingresaron, pendientes) |
| `POST` | `/api/seed` | Importar asistentes desde CSV |
| `GET` | `/qr/{filename}` | Servir imagen QR |
| `GET` | `/` | Frontend (scanner HTML) |
| `GET` | `/health` | Health check |

---

## 🚀 Despliegue Rápido

### 1. Prerrequisitos

- Servidor Ubuntu con Docker y Docker Compose instalados
- Dominio DNS apuntando al servidor (ej: `evento.midominio.com`)
- Puerto 80 y 443 abiertos

### 2. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con tus credenciales
nano .env
```

### 3. Generar códigos QR

```bash
# Con datos de muestra (1800 asistentes)
python generate_qr.py

# O con datos reales desde CSV
python generate_qr.py --input mis_asistentes.csv --label
```

Esto genera:
- `qr_codes/` — 1800 imágenes PNG
- `asistentes_import.csv` — CSV listo para importar

### 4. Levantar el stack

```bash
docker compose up -d
```

### 5. Importar datos a la base de datos

```bash
# Copiar el CSV al directorio de datos
cp asistentes_import.csv ./data/  # si no está ya montado

# Importar vía API
curl -X POST https://tu-dominio.com/api/seed
```

### 6. Configurar HTTPS (Let's Encrypt)

```bash
# Editar el script con tu dominio y email
nano init-letsencrypt.sh

# Ejecutar
bash init-letsencrypt.sh
```

Esto:
1. Levanta Nginx con config HTTP-only
2. Obtiene certificado SSL con Certbot
3. Genera la configuración SSL
4. Reinicia todo con HTTPS

### 7. ¡Listo!

Abrir `https://tu-dominio.com` en el celular y empezar a escanear.

---

## 📱 Uso del Scanner

1. Abrir la URL en el celular (Chrome/Safari)
2. Tocar "Activar Cámara"
3. Apuntar al código QR del asistente
4. El sistema muestra:
   - ✅ **Bienvenido** — Primer ingreso exitoso
   - ⚠️ **QR ya utilizado** — Con hora del primer ingreso
   - ❌ **Código Inválido** — Hash no encontrado

### Fallback sin cámara

Si la cámara no funciona, se puede ingresar el código manualmente con el botón "Ingresar código manual".

### QR escaneado con cámara nativa

Si el asistente escanea su propio QR con la cámara del teléfono, la URL se abre directamente y valida automáticamente.

---

## 🗂️ Estructura del Proyecto

```
qr-lnl/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI application
│   │   ├── database.py       # SQLAlchemy async config
│   │   ├── models.py         # Modelos de datos
│   │   ├── schemas.py        # Pydantic schemas
│   │   └── seed.py           # Script de importación CSV
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── index.html            # Scanner HTML/JS
├── nginx/
│   ├── default.conf          # Config HTTP + redirect
│   └── ssl.conf.template     # Template para SSL
├── qr_codes/                 # Imágenes QR generadas
├── generate_qr.py            # Script generador de QR
├── asistentes_import.csv     # CSV de asistentes
├── docker-compose.yml
├── init-letsencrypt.sh       # Script SSL automático
├── .env.example
└── README.md
```

---

## 🔧 Comandos Útiles

### Ver logs

```bash
docker compose logs -f backend
docker compose logs -f nginx
docker compose logs -f db
```

### Reiniciar un servicio

```bash
docker compose restart backend
```

### Acceder a la base de datos

```bash
docker compose exec db psql -U evento -d evento_db
```

### Ver estadísticas por CLI

```bash
curl https://tu-dominio.com/api/stats | jq
```

### Backup de la base de datos

```bash
docker compose exec db pg_dump -U evento evento_db > backup_$(date +%F).sql
```

### Restaurar backup

```bash
docker compose exec -T db psql -U evento evento_db < backup_2024-01-01.sql
```

### Renovar certificado SSL

```bash
docker compose run --rm certbot renew
docker compose exec nginx nginx -s reload
```

O automatizar con cron:

```bash
0 3 * * * cd /ruta/qr-lnl && docker compose run --rm certbot renew --quiet && docker compose exec nginx nginx -s reload
```

---

## 🔒 Seguridad

- **Race conditions**: El backend usa `SELECT ... FOR UPDATE` (row-level locking) para evitar que dos scanners marquen el mismo QR simultáneamente.
- **Hashes UUID**: Cada QR tiene un hash de 16 caracteres hexadecimales (UUID4-based), imposible de adivinar.
- **HTTPS obligatorio**: Todo el tráfico va por HTTPS con certificados Let's Encrypt.
- **Headers de seguridad**: Nginx agrega HSTS, X-Content-Type-Options, X-Frame-Options, etc.
- **CORS**: Configurado para aceptar cualquier origen (la app se sirve del mismo dominio).

---

## ⚡ Performance

- **Backend**: 4 workers de Uvicorn (configurable en Dockerfile)
- **DB**: PostgreSQL con pool de 10 conexiones (max 30)
- **QR images**: Cacheadas por Nginx (7 días)
- **1800 asistentes**: Probado sin problemas con acceso concurrente

---

## 🐛 Troubleshooting

### El scanner no conecta

1. Verificar que el dominio esté accesible: `curl https://tu-dominio.com/health`
2. Ver logs del backend: `docker compose logs backend`
3. Verificar que la DB esté corriendo: `docker compose ps`

### Certificado SSL expirado

```bash
docker compose run --rm certbot renew
docker compose exec nginx nginx -s reload
```

### La base de datos no arranca

```bash
docker compose logs db
docker compose down -v  # ¡CUIDADO! Esto borra los datos
docker compose up -d
```

### Los QR no se sirven

Verificar que el directorio `qr_codes/` esté montado correctamente:

```bash
docker compose exec backend ls /app/qr_codes
```

---

## 📄 Licencia

Proyecto interno para control de acceso a eventos.
