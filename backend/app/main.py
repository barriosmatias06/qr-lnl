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
    """Inicializar DB al arrancar."""
    await init_db()
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

            if attendee.estado_ingreso:
                return CheckResponse(
                    status=StatusType.ALREADY_USED,
                    nombre=attendee.nombre,
                    fecha_ingreso=attendee.fecha_ingreso.strftime("%d/%m/%Y %H:%M:%S") if attendee.fecha_ingreso else None,
                )

            # Primer ingreso: marcar y registrar timestamp
            now = datetime.now(timezone.utc)
            attendee.estado_ingreso = True
            attendee.fecha_ingreso = now
            await session.commit()

            return CheckResponse(
                status=StatusType.WELCOME,
                nombre=f"{attendee.nombre} {attendee.apellido}".strip(),
                fecha_ingreso=now.strftime("%d/%m/%Y %H:%M:%S"),
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
    - dominic.com.ar        → redirect a /register (invitados se registran)
    - empleados.dominic.com.ar → scanner QR (personal de seguridad)
    - admin.dominic.com.ar  → redirect a /admin (panel de administración)
    """
    host = request.headers.get("host", "")

    if host.startswith("admin."):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin", status_code=302)

    if host.startswith("empleados."):
        # Scanner para personal de seguridad
        index_path = Path(__file__).parent.parent / "frontend" / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=404, detail="Frontend no encontrado")
        return index_path.read_text(encoding="utf-8")

    # dominic.com.ar → redirect a registro
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/register", status_code=302)


# Health check para Docker / monitoreo
@app.get("/health")
async def health_check():
    return {"status": "ok"}

# ── Register routes ──────────────────────────────────────────────────────
from app.register import router as register_router
app.include_router(register_router)

# ── Auth routes (login/logout) ───────────────────────────────────────────
from app.auth import router as auth_router
app.include_router(auth_router)

# ── Admin routes ──────────────────────────────────────────────────────────
from app.admin import router as admin_router
app.include_router(admin_router)
