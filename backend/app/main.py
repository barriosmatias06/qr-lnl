"""
Backend FastAPI para Control de Acceso a Eventos.
Valida códigos QR, registra asistencia y sirve imágenes QR.
"""

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_engine, async_session, init_db
from app.models import Attendee
from app.schemas import CheckResponse, StatsResponse, StatusType


# ── Configuración ──────────────────────────────────────────────────────────

QR_IMAGES_DIR = Path(os.getenv("QR_IMAGES_DIR", "/app/qr_codes"))


# ── Lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializar DB y ejecutar migraciones al arrancar."""
    await init_db()
    # Ejecutar migración de role si es necesario
    try:
        from app.migrate_add_role import migrate
        await migrate()
    except Exception as e:
        print(f"⚠️  Warning: migración de role falló: {e}")
    # Ejecutar migración de campos VIP
    try:
        from app.migrate_vip_fields import migrate
        await migrate()
    except Exception as e:
        print(f"⚠️  Warning: migración VIP falló: {e}")
    # Crear usuarios admin iniciales si no existen
    try:
        from app.seed_admins import seed_admins
        await seed_admins()
    except Exception as e:
        print(f"⚠️  Warning: seed de admins falló: {e}")
    yield


app = FastAPI(
    title="Control de Acceso — Evento",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: permitir cualquier origen (la app se sirve desde el mismo dominio,
# pero puede haber acceso directo por IP durante desarrollo)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Archivos estáticos (flyer, etc.)
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


# ── Endpoints API ──────────────────────────────────────────────────────────

@app.get("/api/check", response_model=CheckResponse)
async def check_attendee(hash: str = Query(..., min_length=8, max_length=64)):
    """
    Valida el hash de un asistente y registra su primer ingreso.
    Usa row-level locking (SELECT ... FOR UPDATE) para evitar race conditions.
    Para VIP: verifica que el pago esté confirmado antes de permitir ingreso.
    Busca por qr_token o hash_unique (compatibilidad hacia atrás).
    """
    hash_clean = hash.strip().upper()

    if not hash_clean:
        return CheckResponse(status=StatusType.INVALID, message="Hash vacío o inválido")

    async with async_session() as session:
        async with session.begin():
            stmt = (
                select(Attendee)
                .where(
                    (Attendee.qr_token == hash_clean) | (Attendee.hash_unique == hash_clean)
                )
                .with_for_update()  # row-level lock
            )
            result = await session.execute(stmt)
            attendee = result.scalar_one_or_none()

            if not attendee:
                return CheckResponse(status=StatusType.INVALID, message="Código no encontrado")

            # ── Verificar VIP: ¿pago confirmado? ──────────────────────
            if attendee.tipo_acceso == "VIP" and not attendee.pago_confirmado:
                # VIP sin pago: crear preferencia si no existe
                init_point = None
                if attendee.mp_preference_id:
                    # Intentar obtener el init_point existente
                    from app.mp import mp_request
                    try:
                        resp = await mp_request("GET", f"/checkout/preferences/{attendee.mp_preference_id}")
                        if resp.status_code == 200:
                            init_point = resp.json().get("init_point")
                    except Exception:
                        pass

                return CheckResponse(
                    status=StatusType.PAYMENT_REQUIRED,
                    nombre=f"{attendee.nombre} {attendee.apellido}".strip(),
                    tipo_acceso="VIP",
                    pago_confirmado=False,
                    mp_preference_id=attendee.mp_preference_id,
                    mp_init_point=init_point,
                    message="Pago VIP requerido para ingresar",
                )

            # ── Primer ingreso: marcar y registrar timestamp ──────────
            if attendee.estado_ingreso:
                return CheckResponse(
                    status=StatusType.ALREADY_USED,
                    nombre=f"{attendee.nombre} {attendee.apellido}".strip(),
                    fecha_ingreso=attendee.fecha_ingreso.strftime("%d/%m/%Y %H:%M:%S") if attendee.fecha_ingreso else None,
                    tipo_acceso=attendee.tipo_acceso,
                    pago_confirmado=attendee.pago_confirmado,
                )

            # Registrar ingreso
            now = datetime.now(timezone.utc)
            attendee.estado_ingreso = True
            attendee.fecha_ingreso = now
            await session.commit()

            return CheckResponse(
                status=StatusType.WELCOME,
                nombre=f"{attendee.nombre} {attendee.apellido}".strip(),
                fecha_ingreso=now.strftime("%d/%m/%Y %H:%M:%S"),
                tipo_acceso=attendee.tipo_acceso,
                pago_confirmado=attendee.pago_confirmado,
            )


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """Estadísticas de asistencia."""
    async with async_session() as session:
        total_stmt = select(func.count(Attendee.id))
        ingresados_stmt = select(func.count(Attendee.id)).where(Attendee.estado_ingreso.is_(True))

        total = (await session.execute(total_stmt)).scalar() or 0
        ingresaron = (await session.execute(ingresados_stmt)).scalar() or 0

        return StatsResponse(
            total=total,
            ingresaron=ingresaron,
            pendientes=total - ingresaron,
        )


@app.post("/api/seed")
async def seed_database():
    """
    Endpoint administrativo para importar datos desde CSV.
    Solo disponible si la tabla está vacía (protección básica).
    """
    from app.seed import seed_from_csv

    async with async_session() as session:
        stmt = select(func.count(Attendee.id))
        count = (await session.execute(stmt)).scalar() or 0

        if count > 0:
            raise HTTPException(status_code=409, detail="La base de datos ya tiene datos. Use otro método para actualizar.")

        try:
            inserted = await seed_from_csv(session)
            return {"message": f"Se importaron {inserted} asistentes correctamente."}
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="No se encontró el CSV de asistentes.")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


# ── Serving de imágenes QR ────────────────────────────────────────────────

@app.get("/qr/{filename}")
async def serve_qr_image(filename: str):
    """Sirve una imagen QR desde el directorio montado."""
    file_path = QR_IMAGES_DIR / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Imagen QR no encontrada")
    return FileResponse(file_path, media_type="image/png")


# ── Frontend (SPA) ─────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """Ruteo por dominio:
    - dominic.com.ar            → redirect a /register (invitados se registran)
    - panel.dominic.com.ar      → scanner QR + panel admin (personal del evento)
    - admin.dominic.com.ar      → redirect a panel.dominic.com.ar/admin
    """
    host = request.headers.get("host", "")
    from fastapi.responses import RedirectResponse

    if host.startswith("admin."):
        # Redirige al panel admin en el subdominio panel
        domain = host.replace("admin.", "panel.")
        return RedirectResponse(url=f"https://{domain}/admin", status_code=302)

    if host.startswith("panel."):
        # Scanner para personal de seguridad
        index_path = Path(__file__).parent.parent / "frontend" / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=404, detail="Frontend no encontrado")
        return index_path.read_text(encoding="utf-8")

    # dominic.com.ar → redirect a registro
    return RedirectResponse(url="/register", status_code=302)


# Health check para Docker / monitoreo
@app.get("/health")
async def health_check():
    return {"status": "ok"}

# ── Seed admin users ─────────────────────────────────────────────────────
@app.post("/api/seed-admins")
async def seed_admin_users():
    """Crear usuarios admin iniciales si no existen."""
    from app.seed_admins import seed_admins
    try:
        await seed_admins()
        return {"message": "Usuarios admin creados correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Register routes ──────────────────────────────────────────────────────
from app.register import router as register_router
app.include_router(register_router)

# ── Auth routes (login/logout) ───────────────────────────────────────────
from app.auth import router as auth_router
app.include_router(auth_router)

# ── Admin routes ──────────────────────────────────────────────────────────
from app.admin import router as admin_router
app.include_router(admin_router)

# ── Mercado Pago routes ──────────────────────────────────────────────────
from app.mp import router as mp_router
app.include_router(mp_router)
